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
# HELPERS
# =============================
def normalize_text(text):
    return re.sub(r"[\s\.\-\/\:\,\(\)\[\]_]+", "", text.upper())


def match_date(text, selected_date):
    text_clean = normalize_text(text)

    dt = datetime.strptime(selected_date, "%d %b %Y")

    month = dt.strftime("%b").upper()
    days = [str(dt.day), f"{dt.day:02}"]
    years = [str(dt.year), str(dt.year)[-2:]]

    patterns = [
        f"{day}{month}{year}"
        for day in days
        for year in years
    ]

    return any(pattern in text_clean for pattern in patterns)


def extract_section_detail(text):
    """
    Detects AIP section details from page text.

    Returns:
        {
            "section": "GEN" / "ENR" / "AD",
            "major": integer or None,
            "raw": matched text
        }
    """
    t = text.upper()

    patterns = [
        r"\b(GEN)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]?\s*\d+)?\b",
        r"\b(ENR)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]?\s*\d+)?\b",
        r"\b(AD)\s*[\.\-]?\s*(\d+)(?:\s*[\.\-]?\s*\d+)?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, t)
        if match:
            return {
                "section": match.group(1),
                "major": int(match.group(2)),
                "raw": match.group(0)
            }

    section_only_patterns = [
        r"\b(GEN)\b",
        r"\b(ENR)\b",
        r"\b(AD)\b",
    ]

    for pattern in section_only_patterns:
        match = re.search(pattern, t)
        if match:
            return {
                "section": match.group(1),
                "major": None,
                "raw": match.group(0)
            }

    return {
        "section": None,
        "major": None,
        "raw": None
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

    if section and major:
        return f"{section} {major}"

    if section:
        return section

    return "Other / Unrecognized Pages"


def is_auto_removed_section(section_detail):
    """
    Auto-removes these AIP sections and all their subsections,
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


def get_header_footer_text(page):
    """
    Extracts text only from page header and footer areas.
    Used for ICAO detection on AD pages.
    """
    blocks = page.get_text("blocks")
    page_height = page.rect.height

    header_footer_parts = []

    for block in blocks:
        x0, y0, x1, y1, text = block[:5]

        if y0 < 140 or y1 > page_height - 140:
            header_footer_parts.append(str(text))

    return " ".join(header_footer_parts).upper()


def extract_icaos_from_header_footer(page):
    """
    Extracts all 4-letter ICAO-like codes from header/footer area.
    Final filtering compares directly against master airport sheet.
    """
    header_footer_text = get_header_footer_text(page)

    detected = set()

    strong_patterns = [
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

        section_detail = extract_section_detail(text)
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
        if section == "AD":
            page_icaos = extract_icaos_from_header_footer(page)

            all_icaos.update(page_icaos)

            page_kept_icaos = {
                code for code in page_icaos
                if code in allowed_icaos
            }

            page_removed_icaos = page_icaos - page_kept_icaos

            kept_icaos.update(page_kept_icaos)
            removed_icaos.update(page_removed_icaos)

            ad_page_icao_map[page_index] = {
                "all": page_icaos,
                "kept": page_kept_icaos,
                "removed": page_removed_icaos
            }

    final_pages = []

    for page_index, page, text, section, section_detail in temp_pages:
        if section == "AD":
            page_data = ad_page_icao_map.get(
                page_index,
                {
                    "all": set(),
                    "kept": set(),
                    "removed": set()
                }
            )

            if not page_data["all"]:
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
