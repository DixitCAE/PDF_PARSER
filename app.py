import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter


# =============================
# PAGE CONFIG
# =============================
st.set_page_config(
    page_title="AIP Trimmer",
    page_icon="✈️",
    layout="wide"
)


# =============================
# PREMIUM UI CSS
# =============================
st.markdown(
    """
    <style>
        .main {
            background-color: #f7f9fc;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        .kpi-card {
            background: linear-gradient(135deg, #ffffff, #f2f6ff);
            border: 1px solid #dce6f5;
            border-radius: 18px;
            padding: 20px;
            box-shadow: 0 8px 20px rgba(31, 60, 136, 0.08);
            text-align: center;
            margin-bottom: 10px;
        }

        .kpi-card h4 {
            margin: 0;
            color: #5f6f89;
            font-size: 15px;
            font-weight: 600;
        }

        .kpi-card h2 {
            margin: 8px 0 0 0;
            color: #102a43;
            font-size: 34px;
            font-weight: 800;
        }

        .side-panel {
            background: #ffffff;
            border: 1px solid #e3eaf5;
            border-radius: 18px;
            padding: 18px;
            box-shadow: 0 8px 18px rgba(31, 60, 136, 0.08);
        }

        .plane-animation {
            font-size: 54px;
            animation: fly 1.8s linear infinite;
            white-space: nowrap;
            overflow: hidden;
        }

        @keyframes fly {
            0% {
                transform: translateX(-15%);
            }
            100% {
                transform: translateX(105%);
            }
        }

        .enr-subsection-title {
            font-size: 13px;
            color: #8ea2c8;
            margin-top: -4px;
            margin-bottom: 4px;
            margin-left: 38px;
            font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# =============================
# MASTER CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"


@st.cache_data(show_spinner=False)
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(
        df[0]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )


# =============================
# TEXT HELPERS
# =============================
def normalize_text(text):
    return re.sub(r"[\s\.\-\/\:\,\(\)\[\]_]+", "", str(text).upper())


def compact_spaces(text):
    return re.sub(r"\s+", " ", str(text).upper()).strip()


def match_date(text, selected_date):
    """
    Matches normal AIP effective dates and China-style numeric EFF timestamps.

    Existing supported examples:
        05-AUG-2026
        05 AUG 2026
        05AUG2026
        05AUG26
        5AUG2026
        5AUG26

    China supported examples:
        EFF2608051600
        2608051600
        EFF202608051600
        202608051600

    China time is fixed as 1600 based on current observed document format.
    """
    text_clean = normalize_text(text)

    dt = datetime.strptime(selected_date, "%d %b %Y")

    month = dt.strftime("%b").upper()
    days = [str(dt.day), f"{dt.day:02}"]
    years = [str(dt.year), str(dt.year)[-2:]]

    normal_patterns = [
        f"{day}{month}{year}"
        for day in days
        for year in years
    ]

    china_yymmdd_time = dt.strftime("%y%m%d") + "1600"
    china_yyyymmdd_time = dt.strftime("%Y%m%d") + "1600"

    china_patterns = [
        china_yymmdd_time,
        f"EFF{china_yymmdd_time}",
        china_yyyymmdd_time,
        f"EFF{china_yyyymmdd_time}"
    ]

    patterns = normal_patterns + china_patterns

    return any(pattern in text_clean for pattern in patterns)


# =============================
# PAGE TITLE / SECTION DETECTION
# =============================
def get_zone_lines(page, top_limit=150, bottom_limit=120):
    """
    Extracts text lines from top header and bottom footer zones.

    Important:
    - Reads left, center, and right side.
    - Uses vertical position only.
    - Keeps line order by y-position and x-position.
    """
    lines = []
    page_height = page.rect.height

    try:
        page_dict = page.get_text("dict")
    except Exception:
        return []

    for block in page_dict.get("blocks", []):
        if "lines" not in block:
            continue

        for line in block.get("lines", []):
            line_bbox = line.get("bbox", [0, 0, 0, 0])
            x0, y0, x1, y1 = line_bbox

            if not (y0 < top_limit or y1 > page_height - bottom_limit):
                continue

            spans_text = []

            for span in line.get("spans", []):
                span_text = span.get("text", "")
                if span_text:
                    spans_text.append(span_text)

            line_text = compact_spaces(" ".join(spans_text))

            if line_text:
                lines.append((y0, x0, line_text))

    lines.sort(key=lambda item: (item[0], item[1]))

    return [line_text for _, _, line_text in lines]


def get_title_area_text(page):
    lines = get_zone_lines(page)
    return compact_spaces(" ".join(lines))


def match_generic_section_title(line_text):
    """
    Detects actual generic AIP section title lines:
        GEN 0.4 - 1
        ENR 1.10 - 2
        AD 0.6 - 3
        AD 1.3 - 5

    This does not detect airport owner ICAO.
    """
    t = compact_spaces(line_text)

    generic_title_patterns = [
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
    ]

    for pattern in generic_title_patterns:
        match = re.search(pattern, t)
        if match:
            return {
                "section": match.group(1),
                "major": int(match.group(2)),
                "raw": match.group(0),
                "icao": None,
                "is_airport_ad": False
            }

    return None


def match_airport_ad_title(line_text):
    """
    Detects actual airport AD page title/header.

    Supported airport title formats:
        LPFR AD 2 - 1
        LPBJ AD 2 - 4
        AIP PORTUGAL LPFR AD 2 - 5
        LPFR AD 2.24.02 - 2
        ZPPP AD2-1
        ZPPP AD2 - 1
        AD 2 SBCT - 10
        AD2 SBCT - 10

    It intentionally avoids insert/remove list patterns like:
        LPFR AD 2 - 1/2
        ZPPP AD2-1~55

    Brazil-specific safety:
        Reverse format AD 2 ICAO - page requires a page number after ICAO.
        This prevents false owner ICAO from generic text like AD 2 AERODROMES.
    """
    t = compact_spaces(line_text)

    airport_ad_patterns = [
        # Brazil / reverse order: AD 2 SBCT - 10
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?AD\s*2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?AD2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",

        # Standard order: SBCT AD 2 - 10
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?([A-Z]{4})\s+AD\s*2(?:\s*\.\s*\d+)*(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\b([A-Z]{4})\s+AD\s*2(?:\s*\.\s*\d+)*(?:\s*-\s*\d+)?\s+(?:AIP\s*[-]?\s*[A-Z ]+)\b(?!\s*[\/~])",

        # Compact China-style: ZPPP AD2-1
        r"^(?:AIP\s*[-]?\s*[A-Z ]+\s+)?([A-Z]{4})\s+AD2(?:\s*-\s*\d+)?\b(?!\s*[\/~])"
    ]

    for pattern in airport_ad_patterns:
        match = re.search(pattern, t)
        if match:
            return {
                "section": "AD",
                "major": 2,
                "raw": match.group(0),
                "icao": match.group(1),
                "is_airport_ad": True
            }

    return None


def extract_section_detail_from_page(page):
    """
    Main section detection.

    Priority:
    1. Actual airport AD page title/header first.
       - ICAO AD 2 format.
       - AD 2 ICAO format.
    2. Actual generic section title/header.
       - GEN, ENR, AD 0/1 etc.
    3. Fallback to generic section detection only.
       - Fallback does not create airport-owner ICAO from random body/list text.

    This prevents:
    - AD pages with body references like GEN-3.1 being wrongly auto-removed.
    - Non-master airport pages being kept because another master airport is mentioned in the body.
    - Brazil AD 2 ICAO headers being treated as AD 2 with missing owner ICAO.
    """
    title_lines = get_zone_lines(page)

    for line in title_lines[:8]:
        airport_detail = match_airport_ad_title(line)
        if airport_detail:
            return airport_detail

        generic_detail = match_generic_section_title(line)
        if generic_detail:
            return generic_detail

    joined_title = compact_spaces(" ".join(title_lines[:8]))

    airport_detail = match_airport_ad_title(joined_title)
    if airport_detail:
        return airport_detail

    generic_detail = match_generic_section_title(joined_title)
    if generic_detail:
        return generic_detail

    full_text = compact_spaces(page.get_text()[:1500])

    fallback_patterns = [
        r"\b(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
    ]

    for pattern in fallback_patterns:
        match = re.search(pattern, full_text)
        if match:
            return {
                "section": match.group(1),
                "major": int(match.group(2)),
                "raw": match.group(0),
                "icao": None,
                "is_airport_ad": False
            }

    section_only_patterns = [
        r"\b(GEN)\b",
        r"\b(ENR)\b",
        r"\b(AD)\b",
    ]

    for pattern in section_only_patterns:
        match = re.search(pattern, full_text)
        if match:
            return {
                "section": match.group(1),
                "major": None,
                "raw": match.group(0),
                "icao": None,
                "is_airport_ad": False
            }

    return {
        "section": None,
        "major": None,
        "raw": None,
        "icao": None,
        "is_airport_ad": False
    }


def extract_section_detail(text):
    """
    Backward-compatible text-only section detector for old session-state tuples.
    """
    full_text = compact_spaces(str(text)[:1500])

    fallback_patterns = [
        r"\b(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
    ]

    for pattern in fallback_patterns:
        match = re.search(pattern, full_text)
        if match:
            return {
                "section": match.group(1),
                "major": int(match.group(2)),
                "raw": match.group(0),
                "icao": None,
                "is_airport_ad": False
            }

    return {
        "section": None,
        "major": None,
        "raw": None,
        "icao": None,
        "is_airport_ad": False
    }


def get_page_index(page_tuple):
    return page_tuple[0] if len(page_tuple) > 0 else None


def get_page_text(page_tuple):
    return page_tuple[1] if len(page_tuple) > 1 else ""


def get_page_section(page_tuple):
    return page_tuple[2] if len(page_tuple) > 2 else None


def get_page_major(page_tuple):
    if len(page_tuple) > 3:
        return page_tuple[3]

    text = get_page_text(page_tuple)
    detail = extract_section_detail(text)
    return detail.get("major")


def get_clean_removed_category(section_detail):
    section = section_detail.get("section")
    major = section_detail.get("major")

    if section and major is not None:
        return f"{section} {major}"

    if section:
        return section

    return "Other / Unrecognized Pages"


def is_auto_removed_section(section_detail):
    """
    Auto-removes only actual titled AIP sections and all their subsections,
    regardless of selected effective date:

        GEN 1, GEN 2, GEN 3, GEN 4, GEN 5
        ENR 2, ENR 5, ENR 6
    """
    section = section_detail.get("section")
    major = section_detail.get("major")

    if section == "GEN" and major in {1, 2, 3, 4, 5}:
        return True

    if section == "ENR" and major in {2, 5, 6}:
        return True

    return False


# =============================
# ICAO / AIRPORT OWNER HELPERS
# =============================
def get_header_footer_text(page):
    """
    Extracts text from header and footer areas.

    Reads left, center, and right side, anywhere horizontally.
    """
    return get_title_area_text(page)


def extract_icaos_from_header_footer(page):
    """
    Extracts all ICAO-like codes from header/footer area.

    This remains available for diagnostics/internal counts, but AD page keep/remove
    now uses only the owner ICAO from the actual AD page title/header.
    """
    header_footer_text = get_header_footer_text(page)

    detected = set()

    strong_patterns = [
        r"\bAD\s*2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",
        r"\bAD2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",
        r"\b([A-Z]{4})\s+AD\s*2(?:\s*\.\s*\d+)*(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\b([A-Z]{4})\s+AD2(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\bAD\s*[\-\.]?\s*2\s*[\-\.]?\s*([A-Z]{4})\b",
        r"\b([A-Z]{4})\s*AD\s*[\-\.]?\s*2\b",
        r"\bAD\s*2\s+([A-Z]{4})\b",
        r"\b([A-Z]{4})\s+AD\s*2\b",
        r"\bAD\s*[\-\.]?\s*2\s*[\/\-\.]\s*([A-Z]{4})\b",
        r"\b([A-Z]{4})\s*[\/\-\.]\s*AD\s*[\-\.]?\s*2\b"
    ]

    for pattern in strong_patterns:
        matches = re.findall(pattern, header_footer_text)
        for match in matches:
            detected.add(match.upper().strip())

    all_four_letter_tokens = re.findall(r"\b[A-Z]{4}\b", header_footer_text)

    noise_tokens = {
        "PAGE",
        "DATE",
        "TIME",
        "AIP",
        "GEN",
        "ENR",
        "NOTE",
        "PART",
        "AIRS",
        "INFO",
        "TEXT",
        "DATA",
        "FROM",
        "WITH",
        "THIS",
        "THAT",
        "AREA",
        "TYPE",
        "NAME",
        "CODE",
        "ZONE",
        "FEET",
        "FTAM",
        "AMDT",
        "SUPP",
        "AIRAC",
        "CIVIL",
        "AUTH",
        "NATL",
        "INTL",
        "CHG",
        "CHGS",
        "TEMP",
        "PERM"
    }

    for token in all_four_letter_tokens:
        token = token.upper().strip()

        if token in noise_tokens:
            continue

        detected.add(token)

    return detected


def get_owner_icao_from_section_detail(section_detail):
    icao = section_detail.get("icao")

    if icao:
        return str(icao).strip().upper()

    return None


def extract_icao(page):
    """
    Backward-compatible helper.
    Returns one ICAO if found.
    """
    codes = extract_icaos_from_header_footer(page)

    if codes:
        return sorted(codes)[0]

    return None


# =============================
# ENR TOGGLE SYNC
# =============================
def sync_enr_subsections():
    """
    When user turns ON the main ENR toggle,
    all available ENR major subsections are automatically turned ON.

    User can manually turn OFF any ENR subsection after that.
    """
    if st.session_state.get("toggle_ENR", False):
        for key in st.session_state.get("enr_subsection_keys", []):
            st.session_state[key] = True


# =============================
# PROCESS PDF
# =============================
def process_pdf(file_bytes, selected_date):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_pdf_pages = len(doc)
    allowed_icaos = load_master()

    temp_pages = []
    auto_removed_pages = []
    removed_page_details = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text()

        section_detail = extract_section_detail_from_page(page)
        section = section_detail["section"]

        if not section:
            removed_page_details.append(
                {
                    "page": page_index + 1,
                    "category": get_clean_removed_category(section_detail)
                }
            )
            continue

        if is_auto_removed_section(section_detail):
            auto_removed_pages.append(
                {
                    "page": page_index + 1,
                    "section": section_detail["section"],
                    "major": section_detail["major"],
                    "raw": section_detail["raw"]
                }
            )

            removed_page_details.append(
                {
                    "page": page_index + 1,
                    "category": get_clean_removed_category(section_detail)
                }
            )
            continue

        if not match_date(text, selected_date):
            removed_page_details.append(
                {
                    "page": page_index + 1,
                    "category": get_clean_removed_category(section_detail)
                }
            )
            continue

        temp_pages.append((page_index, page, text, section, section_detail))

    all_icaos = set()
    kept_icaos = set()
    removed_icaos = set()

    ad_page_icao_map = {}

    for page_index, page, text, section, section_detail in temp_pages:
        if section == "AD" and section_detail.get("major") == 2:
            owner_icao = get_owner_icao_from_section_detail(section_detail)

            if owner_icao:
                all_icaos.add(owner_icao)

                if owner_icao in allowed_icaos:
                    kept_icaos.add(owner_icao)
                    page_kept_icaos = {owner_icao}
                    page_removed_icaos = set()
                else:
                    removed_icaos.add(owner_icao)
                    page_kept_icaos = set()
                    page_removed_icaos = {owner_icao}

                ad_page_icao_map[page_index] = {
                    "owner": owner_icao,
                    "all": {owner_icao},
                    "kept": page_kept_icaos,
                    "removed": page_removed_icaos,
                    "airport_specific": True
                }
            else:
                ad_page_icao_map[page_index] = {
                    "owner": None,
                    "all": set(),
                    "kept": set(),
                    "removed": set(),
                    "airport_specific": True
                }

    final_pages = []

    for page_index, page, text, section, section_detail in temp_pages:
        if section == "AD" and section_detail.get("major") == 2:
            page_data = ad_page_icao_map.get(
                page_index,
                {
                    "owner": None,
                    "all": set(),
                    "kept": set(),
                    "removed": set(),
                    "airport_specific": True
                }
            )

            if not page_data["owner"]:
                removed_page_details.append(
                    {
                        "page": page_index + 1,
                        "category": get_clean_removed_category(section_detail)
                    }
                )
                continue

            if not page_data["kept"]:
                removed_page_details.append(
                    {
                        "page": page_index + 1,
                        "category": get_clean_removed_category(section_detail)
                    }
                )
                continue

        final_pages.append(
            (
                page_index,
                text,
                section,
                section_detail.get("major")
            )
        )

    return (
        doc,
        total_pdf_pages,
        final_pages,
        all_icaos,
        kept_icaos,
        removed_icaos,
        auto_removed_pages,
        removed_page_details
    )


# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, selected_sections, selected_enr_majors):
    output_doc = fitz.open()

    for page_tuple in pages:
        page_index = get_page_index(page_tuple)
        section = get_page_section(page_tuple)
        major = get_page_major(page_tuple)

        if page_index is None:
            continue

        if section == "ENR":
            if "ENR" in selected_sections and major in selected_enr_majors:
                output_doc.insert_pdf(
                    doc,
                    from_page=page_index,
                    to_page=page_index
                )

        elif section in selected_sections:
            output_doc.insert_pdf(
                doc,
                from_page=page_index,
                to_page=page_index
            )

    buffer = BytesIO()
    output_doc.save(buffer)
    buffer.seek(0)

    return buffer


# =============================
# SESSION STATE INIT
# =============================
default_state = {
    "pages": [],
    "total_pdf_pages": 0,
    "all_icaos": set(),
    "kept": set(),
    "removed": set(),
    "auto_removed_pages": [],
    "removed_page_details": [],
    "preview_limit": 10,
    "processed": False,
    "doc": None,
    "selection_initialized": False,
    "enr_subsection_keys": []
}

for key, value in default_state.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =============================
# UI
# =============================
st.title("✈️ AIP Trimmer")

file = st.file_uploader("Upload PDF", type=["pdf"])
date = st.date_input("Effective Date")


# =============================
# RUN PARSER
# =============================
if file:
    if st.button("🚀 Parse"):
        st.session_state.preview_limit = 10
        st.session_state.selection_initialized = False

        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("toggle_"):
                del st.session_state[key]

        plane_box = st.empty()
        plane_box.markdown(
            """
            <div class="plane-animation">✈️</div>
            """,
            unsafe_allow_html=True
        )

        (
            doc,
            total_pdf_pages,
            pages,
            all_icaos,
            kept,
            removed,
            auto_removed_pages,
            removed_page_details
        ) = process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )

        plane_box.empty()

        st.session_state.update(
            {
                "doc": doc,
                "total_pdf_pages": total_pdf_pages,
                "pages": pages,
                "all_icaos": all_icaos,
                "kept": kept,
                "removed": removed,
                "auto_removed_pages": auto_removed_pages,
                "removed_page_details": removed_page_details,
                "processed": True
            }
        )


# =============================
# DISPLAY RESULT
# =============================
if st.session_state.processed:
    pages = st.session_state.pages
    total_pdf_pages = st.session_state.total_pdf_pages
    extracted_pages = len(pages)
    removed_pages = max(total_pdf_pages - extracted_pages, 0)

    present_sections = {
        get_page_section(page)
        for page in pages
        if get_page_section(page)
    }

    present_enr_majors = sorted(
        {
            get_page_major(page)
            for page in pages
            if get_page_section(page) == "ENR" and get_page_major(page) is not None
        }
    )

    enr_subsection_keys = [
        f"toggle_ENR_{major}"
        for major in present_enr_majors
    ]

    if not st.session_state.selection_initialized:
        st.session_state["toggle_GEN"] = False
        st.session_state["toggle_ENR"] = False
        st.session_state["toggle_AD"] = False

        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("toggle_ENR_"):
                del st.session_state[key]

        for major in present_enr_majors:
            st.session_state[f"toggle_ENR_{major}"] = True

        st.session_state.enr_subsection_keys = enr_subsection_keys
        st.session_state.selection_initialized = True
    else:
        st.session_state.enr_subsection_keys = enr_subsection_keys

        for major in present_enr_majors:
            key = f"toggle_ENR_{major}"
            if key not in st.session_state:
                st.session_state[key] = True

    def card(title, value):
        st.markdown(
            f"""
            <div class="kpi-card">
                <h4>{title}</h4>
                <h2>{value}</h2>
            </div>
            """,
            unsafe_allow_html=True
        )

    c1, c2, c3 = st.columns(3)

    with c1:
        card("Pages", total_pdf_pages)

    with c2:
        card("Extracted Pages", extracted_pages)

    with c3:
        card("Removed Pages", removed_pages)

    selected_sections = []
    selected_enr_majors = set()

    if "GEN" in present_sections:
        if st.toggle("GEN", key="toggle_GEN"):
            selected_sections.append("GEN")

    if "ENR" in present_sections:
        if st.toggle(
            "ENR",
            key="toggle_ENR",
            on_change=sync_enr_subsections
        ):
            selected_sections.append("ENR")

            if present_enr_majors:
                st.markdown(
                    """
                    <div class="enr-subsection-title">ENR Major Sections</div>
                    """,
                    unsafe_allow_html=True
                )

                for major in present_enr_majors:
                    sub_key = f"toggle_ENR_{major}"

                    sub_col_space, sub_col_toggle = st.columns([0.04, 0.96])

                    with sub_col_toggle:
                        if st.toggle(
                            f"ENR {major}",
                            key=sub_key
                        ):
                            selected_enr_majors.add(major)

    if "AD" in present_sections:
        if st.toggle("AD", key="toggle_AD"):
            selected_sections.append("AD")

    if not selected_sections:
        st.stop()

    if "ENR" in selected_sections and not selected_enr_majors:
        selected_sections = [
            section
            for section in selected_sections
            if section != "ENR"
        ]

    if not selected_sections:
        st.stop()

    pdf = build_pdf(
        st.session_state.doc,
        pages,
        selected_sections,
        selected_enr_majors
    )

    col_left, col_right = st.columns([3, 1])

    # =============================
    # PREVIEW
    # =============================
    with col_left:
        st.subheader("Preview")

        zoom = st.slider(
            "Zoom",
            min_value=0.5,
            max_value=2.5,
            value=1.0,
            step=0.1
        )

        preview_doc = fitz.open(
            stream=pdf.getvalue(),
            filetype="pdf"
        )

        total_pages = len(preview_doc)
        limit = st.session_state.preview_limit

        for i in range(min(limit, total_pages)):
            pix = preview_doc[i].get_pixmap(
                matrix=fitz.Matrix(2, 2)
            )

            st.image(
                pix.tobytes("png"),
                width=int(700 * zoom)
            )

        if limit < total_pages:
            if st.button("⬇ Load More Pages"):
                st.session_state.preview_limit += 10
                st.rerun()

    # =============================
    # SIDE PANEL
    # =============================
    with col_right:
        st.markdown(
            """
            <div class="side-panel">
            """,
            unsafe_allow_html=True
        )

        st.download_button(
            label="Download PDF",
            data=pdf,
            file_name="trimmed_aip.pdf",
            mime="application/pdf"
        )

        st.markdown("---")
        st.markdown("### Removed Pages Details")

        if st.session_state.removed_page_details:
            removed_counter = Counter(
                [
                    item["category"]
                    for item in st.session_state.removed_page_details
                ]
            )

            displayed_removed_total = 0

            def removed_sort_key(item):
                category = item[0]

                match = re.match(r"^(GEN|ENR|AD)\s+(\d+)$", category)
                if match:
                    section_order = {
                        "GEN": 1,
                        "ENR": 2,
                        "AD": 3
                    }
                    return (
                        section_order.get(match.group(1), 9),
                        int(match.group(2)),
                        category
                    )

                if category == "Other / Unrecognized Pages":
                    return (99, 99, category)

                return (50, 50, category)

            for category, count in sorted(removed_counter.items(), key=removed_sort_key):
                displayed_removed_total += count
                st.write(f"{category}: {count} page(s)")

            if displayed_removed_total != removed_pages:
                st.markdown("---")
                st.warning(
                    f"Removed page mismatch detected: tile shows {removed_pages}, "
                    f"details show {displayed_removed_total}."
                )
        else:
            st.write("No removed pages found")

        st.markdown(
            """
            </div>
            """,
            unsafe_allow_html=True
        )
