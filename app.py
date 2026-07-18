import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from collections import Counter
import tempfile
import uuid
import os


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
# FILE HELPERS
# =============================
def safe_remove_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def cleanup_existing_pdf_files():
    for key in ["input_pdf_path", "output_pdf_path"]:
        path = st.session_state.get(key)
        safe_remove_file(path)


def make_temp_pdf_path(prefix):
    file_id = uuid.uuid4().hex
    return os.path.join(tempfile.gettempdir(), f"{prefix}_{file_id}.pdf")


def save_uploaded_pdf_to_disk(uploaded_file):
    input_path = make_temp_pdf_path("aip_input")

    with open(input_path, "wb") as f:
        f.write(uploaded_file.read())

    return input_path


def get_file_size_mb(path):
    try:
        if path and os.path.exists(path):
            return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0

    return 0


def get_file_mtime(path):
    try:
        if path and os.path.exists(path):
            return os.path.getmtime(path)
    except Exception:
        return 0

    return 0


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
    Fast header/footer text extraction using blocks.

    Reads left, center, and right side.
    Uses vertical position only.
    Preserves approximate line order by y-position and x-position.
    """
    lines = []
    page_height = page.rect.height

    try:
        blocks = page.get_text("blocks")
    except Exception:
        return []

    for block in blocks:
        x0, y0, x1, y1, text = block[:5]

        if not (y0 < top_limit or y1 > page_height - bottom_limit):
            continue

        raw_lines = str(text).splitlines()

        for offset, raw_line in enumerate(raw_lines):
            line_text = compact_spaces(raw_line)

            if line_text:
                lines.append((y0 + offset * 0.01, x0, line_text))

    lines.sort(key=lambda item: (item[0], item[1]))

    return [line_text for _, _, line_text in lines]


def is_administrative_list_page(text):
    """
    Detects amendment cover/checklist/list pages that contain many AD references
    but are not actual airport AD content pages.
    """
    t = compact_spaces(text)

    admin_markers = [
        "DESTROY INSERT",
        "INSERT/DESTROY",
        "INSERIR/DESTRUIR",
        "PAGE TO BE DESTROYED",
        "PAGE TO BE INSERTED",
        "CHECKLIST OF AIP PAGES",
        "LIST OF AERONAUTICAL CHARTS",
        "THIS AIRAC AIP AMDT",
        "CONTAINS:",
        "TO BE INSERTED",
        "TO BE DESTROYED"
    ]

    return any(marker in t for marker in admin_markers)


def match_airport_ad_title(line_text):
    """
    Root-level airport AD title resolver.

    Supported airport page-title formats:
        LPFR AD 2 - 1
        LPFR AD 2.24.01 - 1
        AD 2 SBCT - 10
        AD2 SBCT - 10
        AD 2-WMKP-1-1
        AD 2-WBGB-8-3
        AD2-WMKP-1-1
        ZPPP AD2-1
        ZPPP AD2 - 1
    """
    t = compact_spaces(line_text)

    airport_ad_patterns = [
        r"\bAD\s*2\s*-\s*([A-Z]{4})\s*-\s*\d+(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\bAD2\s*-\s*([A-Z]{4})\s*-\s*\d+(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\bAD\s*2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",
        r"\bAD2\s+([A-Z]{4})\s*-\s*\d+\b(?!\s*[\/~])",
        r"\b([A-Z]{4})\s+AD\s*2(?:\s*\.\s*\d+)*(?:\s*-\s*\d+)?\b(?!\s*[\/~])",
        r"\b([A-Z]{4})\s+AD2(?:\s*-\s*\d+)?\b(?!\s*[\/~])"
    ]

    for pattern in airport_ad_patterns:
        match = re.search(pattern, t)

        if match:
            return {
                "section": "AD",
                "major": 2,
                "raw": match.group(0),
                "icao": match.group(1).upper(),
                "is_airport_ad": True
            }

    return None


def match_generic_section_title(line_text):
    """
    Detects actual generic AIP section title lines:
        GEN 0.4 - 1
        ENR 1.10 - 2
        AD 0.6 - 3
        AD 1.3 - 5
    """
    t = compact_spaces(line_text)

    generic_title_patterns = [
        r"\b(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
        r"\b(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
        r"\b(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*(?:\s*-\s*\d+)?\b",
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


def extract_section_detail_from_page(page, page_text):
    """
    Root-level page identity detection.

    Airport AD title has highest priority only on actual title/header lines.
    Generic section titles protect checklist/list pages from being treated as AD.
    Full-body fallback is used only for generic section detection, never for owner ICAO.
    """
    title_lines = get_zone_lines(page)
    admin_page = is_administrative_list_page(page_text)

    for line in title_lines[:8]:
        airport_detail = match_airport_ad_title(line)

        if airport_detail and not admin_page:
            return airport_detail

        generic_detail = match_generic_section_title(line)

        if generic_detail:
            return generic_detail

    joined_title = compact_spaces(" ".join(title_lines[:8]))

    airport_detail = match_airport_ad_title(joined_title)

    if airport_detail and not admin_page:
        return airport_detail

    generic_detail = match_generic_section_title(joined_title)

    if generic_detail:
        return generic_detail

    limited_text = compact_spaces(page_text[:1500])

    fallback_patterns = [
        r"\b(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
        r"\b(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]\s*\d+)*\b",
    ]

    for pattern in fallback_patterns:
        match = re.search(pattern, limited_text)

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
        match = re.search(pattern, limited_text)

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


def get_page_section(page_tuple):
    return page_tuple[1] if len(page_tuple) > 1 else None


def get_page_major(page_tuple):
    return page_tuple[2] if len(page_tuple) > 2 else None


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
def get_owner_icao_from_section_detail(section_detail):
    icao = section_detail.get("icao")

    if icao:
        return str(icao).strip().upper()

    return None


# =============================
# PREVIEW CACHE
# =============================
@st.cache_data(show_spinner=False, max_entries=300)
def render_preview_page(input_pdf_path, page_index, render_scale, file_mtime):
    """
    Cached page rendering for fast preview.
    file_mtime is included only to invalidate cache when a new uploaded file is saved.
    """
    doc = fitz.open(input_pdf_path)
    page = doc[page_index]

    pix = page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale),
        alpha=False
    )

    image_bytes = pix.tobytes("png")

    doc.close()

    return image_bytes


# =============================
# CALLBACKS
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


def load_more_preview_pages():
    """
    Stable callback for Load More Pages.
    This avoids preview_limit update being lost during Streamlit reruns.
    """
    st.session_state.preview_limit = st.session_state.get("preview_limit", 10) + 10


# =============================
# PROCESS PDF
# =============================
def process_pdf(input_pdf_path, selected_date):
    doc = fitz.open(input_pdf_path)
    total_pdf_pages = len(doc)
    allowed_icaos = load_master()

    temp_pages = []
    auto_removed_pages = []
    removed_page_details = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text()

        section_detail = extract_section_detail_from_page(page, text)
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

        temp_pages.append((page_index, section, section_detail))

    all_icaos = set()
    kept_icaos = set()
    removed_icaos = set()

    ad_page_icao_map = {}

    for page_index, section, section_detail in temp_pages:
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

    for page_index, section, section_detail in temp_pages:
        major = section_detail.get("major")

        if section == "AD" and major == 2:
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
                section,
                major
            )
        )

    doc.close()

    return (
        total_pdf_pages,
        final_pages,
        all_icaos,
        kept_icaos,
        removed_icaos,
        auto_removed_pages,
        removed_page_details
    )


# =============================
# SELECTION HELPERS
# =============================
def get_selected_page_tuples(pages, selected_sections, selected_enr_majors):
    selected_page_tuples = []

    for page_tuple in pages:
        page_index = get_page_index(page_tuple)
        section = get_page_section(page_tuple)
        major = get_page_major(page_tuple)

        if page_index is None:
            continue

        if section == "ENR":
            if "ENR" in selected_sections and major in selected_enr_majors:
                selected_page_tuples.append(page_tuple)

        elif section in selected_sections:
            selected_page_tuples.append(page_tuple)

    return selected_page_tuples


def get_selection_signature(selected_sections, selected_enr_majors):
    return (
        tuple(sorted(selected_sections)),
        tuple(sorted(selected_enr_majors))
    )


def get_preview_signature(selected_preview_indexes, selection_signature):
    """
    Stable signature for preview pagination.
    If selected pages change, preview_limit resets to 10.
    If selected pages do not change, Load More persists.
    """
    return (
        selection_signature,
        len(selected_preview_indexes),
        selected_preview_indexes[0] if selected_preview_indexes else None,
        selected_preview_indexes[-1] if selected_preview_indexes else None
    )


# =============================
# BUILD PDF TO DISK
# =============================
def build_pdf_to_file(input_pdf_path, selected_page_tuples, output_pdf_path):
    source_doc = fitz.open(input_pdf_path)
    output_doc = fitz.open()

    for page_tuple in selected_page_tuples:
        page_index = get_page_index(page_tuple)

        if page_index is None:
            continue

        output_doc.insert_pdf(
            source_doc,
            from_page=page_index,
            to_page=page_index
        )

    page_count = output_doc.page_count

    if page_count == 0:
        output_doc.close()
        source_doc.close()
        safe_remove_file(output_pdf_path)
        return False, 0

    if page_count > 200:
        output_doc.save(
            output_pdf_path,
            garbage=3,
            deflate=True,
            clean=False
        )
    else:
        output_doc.save(
            output_pdf_path,
            garbage=4,
            deflate=True,
            clean=True
        )

    output_doc.close()
    source_doc.close()

    return True, page_count


def prepare_output_pdf(selected_page_tuples, selection_signature):
    input_pdf_path = st.session_state.get("input_pdf_path")

    if not input_pdf_path or not os.path.exists(input_pdf_path):
        return None, 0

    current_output_path = st.session_state.get("output_pdf_path")

    safe_remove_file(current_output_path)

    output_pdf_path = make_temp_pdf_path("trimmed_aip")

    success, output_page_count = build_pdf_to_file(
        input_pdf_path=input_pdf_path,
        selected_page_tuples=selected_page_tuples,
        output_pdf_path=output_pdf_path
    )

    if not success:
        st.session_state.output_pdf_path = None
        st.session_state.output_page_count = 0
        st.session_state.last_selection_signature = None
        return None, 0

    st.session_state.output_pdf_path = output_pdf_path
    st.session_state.output_page_count = output_page_count
    st.session_state.last_selection_signature = selection_signature

    return output_pdf_path, output_page_count


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
    "last_preview_signature": None,
    "processed": False,
    "input_pdf_path": None,
    "output_pdf_path": None,
    "output_page_count": 0,
    "last_selection_signature": None,
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
        st.session_state.last_preview_signature = None
        st.session_state.selection_initialized = False
        st.session_state.last_selection_signature = None
        st.session_state.output_page_count = 0

        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("toggle_"):
                del st.session_state[key]

        cleanup_existing_pdf_files()

        input_pdf_path = save_uploaded_pdf_to_disk(file)

        plane_box = st.empty()
        plane_box.markdown(
            """
            <div class="plane-animation">✈️</div>
            """,
            unsafe_allow_html=True
        )

        (
            total_pdf_pages,
            pages,
            all_icaos,
            kept,
            removed,
            auto_removed_pages,
            removed_page_details
        ) = process_pdf(
            input_pdf_path,
            date.strftime("%d %b %Y")
        )

        plane_box.empty()

        st.session_state.update(
            {
                "input_pdf_path": input_pdf_path,
                "output_pdf_path": None,
                "output_page_count": 0,
                "last_selection_signature": None,
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

    selection_signature = get_selection_signature(
        selected_sections,
        selected_enr_majors
    )

    selected_page_tuples = get_selected_page_tuples(
        pages=pages,
        selected_sections=selected_sections,
        selected_enr_majors=selected_enr_majors
    )

    if not selected_page_tuples:
        st.warning("No pages available for the selected section filters.")
        st.stop()

    selected_preview_indexes = [
        get_page_index(page_tuple)
        for page_tuple in selected_page_tuples
        if get_page_index(page_tuple) is not None
    ]

    preview_signature = get_preview_signature(
        selected_preview_indexes,
        selection_signature
    )

    if st.session_state.last_preview_signature != preview_signature:
        st.session_state.preview_limit = 10
        st.session_state.last_preview_signature = preview_signature

    if st.session_state.last_selection_signature != selection_signature:
        safe_remove_file(st.session_state.get("output_pdf_path"))
        st.session_state.output_pdf_path = None
        st.session_state.output_page_count = 0
        st.session_state.last_selection_signature = None

    col_left, col_right = st.columns([3, 1])

    # =============================
    # PREVIEW FROM ORIGINAL PDF
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

        total_preview_pages = len(selected_preview_indexes)
        limit = st.session_state.preview_limit

        st.caption(
            f"Showing {min(limit, total_preview_pages)} of {total_preview_pages} selected page(s)"
        )

        render_scale = 1.2 if total_preview_pages > 100 else 2.0
        file_mtime = get_file_mtime(st.session_state.input_pdf_path)

        for page_index in selected_preview_indexes[:min(limit, total_preview_pages)]:
            image_bytes = render_preview_page(
                st.session_state.input_pdf_path,
                page_index,
                render_scale,
                file_mtime
            )

            st.image(
                image_bytes,
                width=int(700 * zoom)
            )

        if limit < total_preview_pages:
            st.button(
                "⬇ Load More Pages",
                key="load_more_pages_button",
                on_click=load_more_preview_pages
            )

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

        st.caption(
            f"Selected for output: {len(selected_page_tuples)} page(s)"
        )

        prepare_clicked = st.button("Prepare Download")

        if prepare_clicked:
            with st.spinner("Preparing trimmed PDF..."):
                prepare_output_pdf(
                    selected_page_tuples=selected_page_tuples,
                    selection_signature=selection_signature
                )

        output_pdf_path = st.session_state.get("output_pdf_path")
        output_page_count = st.session_state.get("output_page_count", 0)

        if (
            output_pdf_path
            and os.path.exists(output_pdf_path)
            and st.session_state.get("last_selection_signature") == selection_signature
        ):
            output_size_mb = get_file_size_mb(output_pdf_path)

            st.caption(
                f"Output ready: {output_page_count} page(s), {output_size_mb:.2f} MB"
            )

            with open(output_pdf_path, "rb") as download_file:
                st.download_button(
                    label="Download PDF",
                    data=download_file,
                    file_name="trimmed_aip.pdf",
                    mime="application/pdf"
                )
        else:
            st.caption("Click Prepare Download after finalizing section filters.")

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
