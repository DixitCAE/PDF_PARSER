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

        .removed-icao {
            background: #fff5f5;
            color: #b42318;
            padding: 6px 10px;
            border-radius: 10px;
            margin-bottom: 5px;
            font-weight: 600;
            border: 1px solid #ffd6d6;
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

    Examples detected:
        GEN 1
        GEN 1.1
        GEN-1-2
        GEN.1.3
        ENR 5
        ENR 5.1
        AD 2
        AD-2
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

    return {
        "section": None,
        "major": None,
        "raw": None
    }


def extract_section(text):
    detail = extract_section_detail(text)
    return detail["section"]


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


def extract_icao(page):
    blocks = page.get_text("blocks")

    header_text = " ".join(
        [block[4] for block in blocks if block[1] < 120]
    ).upper()

    patterns = [
        r"AD\s*[\-\.]?\s*2\s*[\-\.]?\s*([A-Z]{4})",
        r"([A-Z]{4})\s*AD\s*2",
        r"\b([A-Z]{4})\b\s+AD\s*[\-\.]?\s*2",
        r"AD\s*2\s+([A-Z]{4})"
    ]

    for pattern in patterns:
        match = re.search(pattern, header_text)
        if match:
            return match.group(1)

    return None


def detect_prefix(icaos):
    if not icaos:
        return None

    return Counter([icao[:2] for icao in icaos]).most_common(1)[0][0]


# =============================
# PROCESS PDF
# =============================
def process_pdf(file_bytes, selected_date):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    allowed_icaos = load_master()

    temp_pages = []
    auto_removed_pages = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text()

        section_detail = extract_section_detail(text)
        section = section_detail["section"]

        if not section:
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
            continue

        if not match_date(text, selected_date):
            continue

        temp_pages.append((page_index, page, text, section))

    raw_icaos = set()

    for _, page, _, section in temp_pages:
        if section == "AD":
            code = extract_icao(page)
            if code:
                raw_icaos.add(code)

    prefix = detect_prefix(raw_icaos)

    all_icaos = {
        code for code in raw_icaos
        if prefix and code.startswith(prefix)
    }

    kept_icaos = {
        code for code in all_icaos
        if code in allowed_icaos
    }

    removed_icaos = all_icaos - kept_icaos

    final_pages = []

    for page_index, page, text, section in temp_pages:
        if section == "AD":
            code = extract_icao(page)

            if not code or code not in kept_icaos:
                continue

        final_pages.append((page_index, text, section))

    return doc, final_pages, all_icaos, kept_icaos, removed_icaos, auto_removed_pages


# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, selected_sections):
    output_doc = fitz.open()

    for page_index, _, section in pages:
        if section in selected_sections:
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
    "all_icaos": set(),
    "kept": set(),
    "removed": set(),
    "auto_removed_pages": [],
    "preview_limit": 10,
    "processed": False,
    "doc": None
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

        plane_box = st.empty()
        plane_box.markdown(
            """
            <div class="plane-animation">✈️</div>
            """,
            unsafe_allow_html=True
        )

        doc, pages, all_icaos, kept, removed, auto_removed_pages = process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )

        plane_box.empty()

        st.session_state.update(
            {
                "doc": doc,
                "pages": pages,
                "all_icaos": all_icaos,
                "kept": kept,
                "removed": removed,
                "auto_removed_pages": auto_removed_pages,
                "processed": True
            }
        )


# =============================
# DISPLAY RESULT
# =============================
if st.session_state.processed:
    pages = st.session_state.pages

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

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        card("Pages", len(pages))

    with c2:
        card("ICAOs", len(st.session_state.all_icaos))

    with c3:
        card("Kept", len(st.session_state.kept))

    with c4:
        card("Removed", len(st.session_state.removed))

    with c5:
        card("Auto Removed", len(st.session_state.auto_removed_pages))

    present_sections = {page[2] for page in pages}

    selected_sections = []

    for section in ["GEN", "ENR", "AD"]:
        if section in present_sections:
            if st.toggle(section):
                selected_sections.append(section)

    if not selected_sections:
        st.stop()

    pdf = build_pdf(
        st.session_state.doc,
        pages,
        selected_sections
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

        st.markdown("### Removed ICAOs")

        if st.session_state.removed:
            for icao in sorted(st.session_state.removed):
                st.markdown(
                    f"""
                    <div class="removed-icao">{icao}</div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.write("No removed ICAOs")

        st.markdown("---")
        st.markdown("### Auto Removed Sections")

        if st.session_state.auto_removed_pages:
            auto_removed_counter = Counter(
                [
                    f"{item['section']} {item['major']}"
                    for item in st.session_state.auto_removed_pages
                ]
            )

            for section_name, count in sorted(auto_removed_counter.items()):
                st.write(f"{section_name}: {count} page(s)")
        else:
            st.write("No auto-removed section pages found")

        st.markdown(
            """
            </div>
            """,
            unsafe_allow_html=True
        )
