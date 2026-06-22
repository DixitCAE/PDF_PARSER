import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO

# =============================
# ✅ GITHUB CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data(ttl=300)
def load_master_airports():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df.iloc[:, 0].dropna().astype(str).str.strip().str.upper())


# =============================
# SESSION STATE INIT
# =============================
if "processed" not in st.session_state:
    st.session_state.processed = False
if "pages" not in st.session_state:
    st.session_state.pages = []
if "doc" not in st.session_state:
    st.session_state.doc = None
if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10
if "kept_icaos" not in st.session_state:
    st.session_state.kept_icaos = set()
if "removed_icaos" not in st.session_state:
    st.session_state.removed_icaos = set()


# =============================
# DATE MATCH
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")

    d1, d2 = str(dt.day), f"{dt.day:02}"
    m = dt.strftime("%b").upper()
    y_full, y_short = str(dt.year), str(dt.year)[-2:]

    patterns = [
        f"{d1}{m}{y_full}", f"{d2}{m}{y_full}",
        f"{m}{d1}{y_full}", f"{m}{d2}{y_full}",
        f"{d1}{m}{y_short}", f"{d2}{m}{y_short}",
        f"{m}{d1}{y_short}", f"{m}{d2}{y_short}",
    ]

    return any(p in text for p in patterns)


# =============================
# TEXT EXTRACTION
# =============================
def extract_fast_text(page):
    return " ".join([b[4] for b in page.get_text("blocks")])


# =============================
# SECTION DETECT
# =============================
def extract_section(text):
    text = text.upper()

    m = re.search(r'(GEN\s*\d+(\.\d+)?)|(ENR\s*\d+(\.\d+)?)', text)
    if m:
        return re.sub(r"\s+", " ", m.group()).strip()

    if "AD" in text:
        m_ad = re.search(r'AD\s*(\d+)', text)
        if m_ad:
            return f"AD {m_ad.group(1)}"
        return "AD"

    return None


# =============================
# REMOVE RULES
# =============================
def should_remove(section):
    if not section:
        return True

    rules = [
        "GEN 0", "GEN 2", "GEN 3", "GEN 4",
        "ENR 0", "ENR 2", "ENR 6",
        "AD 3"
    ]
    return any(section.startswith(r) for r in rules)


# =============================
# PROCESS PDF (WITH ICAO TRACKING)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    cleaned_pages = []

    allowed_airports = load_master_airports()

    all_icaos = set()
    kept_icaos = set()

    for i in range(len(doc)):

        page = doc[i]
        text = extract_fast_text(page)

        if not match_date(text, selected_date):
            continue

        sec = extract_section(text)

        if should_remove(sec):
            continue

        if sec and sec.startswith("AD"):

            codes = re.findall(r'\b[A-Z]{4}\b', text.upper())

            for code in codes:
                all_icaos.add(code)

            match = False
            for code in codes:
                if code in allowed_airports:
                    kept_icaos.add(code)
                    match = True

            if not match:
                continue

        cleaned_pages.append((i, text))

    removed_icaos = all_icaos - kept_icaos

    return doc, cleaned_pages, kept_icaos, removed_icaos


# =============================
# BUILD PDF
# =============================
def build_filtered_pdf(doc, pages, selected_sections):

    final_pages = []

    for page_num, text in pages:

        sec = extract_section(text)

        for sel in selected_sections:
            if sec and sec.startswith(sel):
                final_pages.append(page_num)
                break

    final_pages = sorted(set(final_pages))

    output = fitz.open()
    for p in final_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)
    buffer.seek(0)

    return buffer, len(final_pages)


# =============================
# UI
# =============================
st.set_page_config(layout="wide")
st.title("✈️ Universal PDF Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")


# =============================
# EXTRACT
# =============================
if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("🛫 Processing the request..."):

            doc, pages, kept, removed = process_pdf(
                uploaded_file.read(),
                selected_date.strftime("%d %b %Y")
            )

            st.session_state.doc = doc
            st.session_state.pages = pages
            st.session_state.kept_icaos = kept
            st.session_state.removed_icaos = removed
            st.session_state.processed = True
            st.session_state.preview_limit = 10


# =============================
# MAIN DISPLAY
# =============================
if st.session_state.processed:

    doc = st.session_state.doc
    pages = st.session_state.pages

    if len(pages) == 0:
        st.warning("⚠️ There are no important sections to be reviewed.")
        st.stop()

    st.success(f"✅ Final Cleaned Pages: {len(pages)}")

    # ✅ ICAO DASHBOARD
    kept = st.session_state.kept_icaos
    removed = st.session_state.removed_icaos

    colA, colB = st.columns(2)

    with colA:
        if kept:
            st.success(f"✅ Kept Airports: {len(kept)}")

    with colB:
        if removed:
            st.warning(f"❌ Removed Airports: {len(removed)}")

    if removed:
        with st.expander("View Removed ICAOs"):
            st.text(", ".join(sorted(removed)))

    # GROUP
    sections = {"GEN": [], "ENR": [], "AD": []}

    for _, text in pages:
        sec = extract_section(text)

        if sec:
            if sec.startswith("GEN"):
                sections["GEN"].append(sec)
            elif sec.startswith("ENR"):
                sections["ENR"].append(sec)
            elif sec.startswith("AD"):
                sections["AD"].append("AD")

    for k in sections:
        sections[k] = sorted(set(sections[k]))

    st.subheader("📌 Filter by Section")

    selected_sections = []

    if sections["GEN"]:
        with st.expander("GEN", expanded=False):
            for sec in sections["GEN"]:
                if st.checkbox(sec, key=f"G_{sec}"):
                    selected_sections.append(sec)

    if sections["ENR"]:
        with st.expander("ENR", expanded=False):
            for sec in sections["ENR"]:
                if st.checkbox(sec, key=f"E_{sec}"):
                    selected_sections.append(sec)

    if sections["AD"]:
        with st.expander("AD", expanded=False):
            if st.checkbox("AD", key="A_main"):
                selected_sections.append("AD")

    if not selected_sections:
        st.info("📌 Select a section to preview the extracted pages.")
        st.stop()

    st.markdown(f"### ✅ Selected: `{', '.join(selected_sections)}`")

    output_pdf, count = build_filtered_pdf(doc, pages, selected_sections)

    st.success(f"✅ Final Pages: {count}")

    col_preview, col_download = st.columns([3, 1])

    # PREVIEW
    with col_preview:
        st.subheader("📄 Preview")

        preview_doc = fitz.open(stream=output_pdf.getvalue(), filetype="pdf")

        total_pages = len(preview_doc)
        limit = st.session_state.preview_limit

        for i in range(min(limit, total_pages)):
            pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(1, 1))
            st.image(pix.tobytes("png"), caption=f"Page {i+1}")

        preview_doc.close()

        if limit < total_pages:
            if st.button("📂 Load More Pages"):
                st.session_state.preview_limit += 10
                st.rerun()

    # DOWNLOAD
    with col_download:
        st.subheader("📥 Download")

        st.download_button(
            "Download PDF",
            data=output_pdf,
            file_name="Filtered_AIP.pdf",
            mime="application/pdf"
        )
