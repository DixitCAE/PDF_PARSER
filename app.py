import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO

# =============================
# MASTER CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data(ttl=300)
def load_master_airports():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df.iloc[:, 0].dropna().astype(str).str.strip().str.upper())

# =============================
# SESSION STATE
# =============================
if "processed" not in st.session_state:
    st.session_state.processed = False
if "pages" not in st.session_state:
    st.session_state.pages = []
if "doc" not in st.session_state:
    st.session_state.doc = None
if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10
if "all_icaos" not in st.session_state:
    st.session_state.all_icaos = set()
if "kept_icaos" not in st.session_state:
    st.session_state.kept_icaos = set()
if "removed_icaos" not in st.session_state:
    st.session_state.removed_icaos = set()

# =============================
# COUNTRY PREFIX
# =============================
def get_prefix(filename):
    m = re.match(r'([A-Z]{2})', filename.upper())
    return m.group(1) if m else None

# =============================
# DATE MATCH
# =============================
def match_date(text, selected_date):
    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")

    patterns = [
        f"{d}{dt.strftime('%b').upper()}{y}"
        for d in [str(dt.day), f"{dt.day:02}"]
        for y in [str(dt.year), str(dt.year)[-2:]]
    ]

    return any(p in text for p in patterns)

# =============================
# TEXT
# =============================
def extract_fast_text(page):
    return " ".join([b[4] for b in page.get_text("blocks")])

# =============================
# SECTION DETECT ✅
# =============================
def extract_section(text):
    t = text.upper()

    if re.search(r'\bGEN\s*\d', t):
        return "GEN"
    if re.search(r'\bENR\s*\d', t):
        return "ENR"
    if re.search(r'\bAD\s*\d', t):
        return "AD"

    return None

# =============================
# REMOVE RULES
# =============================
def should_remove(text):
    t = text.upper()

    rules = [
        r'GEN\s*0', r'GEN\s*2', r'GEN\s*3', r'GEN\s*4',
        r'ENR\s*0', r'ENR\s*2', r'ENR\s*6',
        r'AD\s*3'
    ]

    return any(re.search(r, t) for r in rules)

# =============================
# ✅ ICAO FROM HEADER
# =============================
def extract_header_icao(page, prefix):

    blocks = page.get_text("blocks")

    # focus on header area only (top region)
    header_text = " ".join([b[4] for b in blocks if b[1] < 120]).upper()

    patterns = [
        r'AD\s*[-\.]?\s*2\s*[-\.]?\s*([A-Z]{4})',
        r'([A-Z]{4})\s*AD\s*2'
    ]

    for p in patterns:
        m = re.search(p, header_text)
        if m:
            code = m.group(1)

            if prefix and code.startswith(prefix):
                return code

    return None

# =============================
# PROCESS PDF ✅ FINAL
# =============================
def process_pdf(file_bytes, selected_date, filename):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    allowed = load_master_airports()
    prefix = get_prefix(filename)

    filtered_pages = []

    # STEP 1: FILTER PAGES
    for i in range(len(doc)):

        page = doc[i]
        text = extract_fast_text(page)

        if not match_date(text, selected_date):
            continue

        if should_remove(text):
            continue

        sec = extract_section(text)

        if sec:
            filtered_pages.append((i, page, text, sec))

    # STEP 2: ICAO EXTRACTION (AD ONLY)
    all_icaos = set()

    for _, page, _, sec in filtered_pages:

        if sec == "AD":
            icao = extract_header_icao(page, prefix)

            if icao:
                all_icaos.add(icao)

    kept_icaos = {c for c in all_icaos if c in allowed}
    removed_icaos = all_icaos - kept_icaos

    # STEP 3: FINAL FILTER
    cleaned_pages = []

    for p, page, text, sec in filtered_pages:

        if sec == "AD":

            icao = extract_header_icao(page, prefix)

            # ignore blank/no ICAO pages
            if not icao:
                continue

            if icao not in kept_icaos:
                continue

        cleaned_pages.append((p, text, sec))

    return doc, cleaned_pages, all_icaos, kept_icaos, removed_icaos

# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, sections):

    output = fitz.open()

    for p, _, sec in pages:
        if sec in sections:
            output.insert_pdf(doc, from_page=p, to_page=p)

    buf = BytesIO()
    output.save(buf)
    buf.seek(0)

    return buf

# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

file = st.file_uploader("Upload AIP PDF", type=["pdf"])
date = st.date_input("Select Date")

# =============================
# RUN
# =============================
if file:

    if st.button("🚀 Parse"):

        with st.spinner("Processing..."):

            doc, pages, all_i, kept_i, rem_i = process_pdf(
                file.read(),
                date.strftime("%d %b %Y"),
                file.name
            )

            st.session_state.doc = doc
            st.session_state.pages = pages
            st.session_state.all_icaos = all_i
            st.session_state.kept_icaos = kept_i
            st.session_state.removed_icaos = rem_i
            st.session_state.processed = True
            st.session_state.preview_limit = 10

# =============================
# DISPLAY ✅ FINAL
# =============================
if st.session_state.processed:

    pages = st.session_state.pages

    if not pages:
        st.warning("No valid sections found")
        st.stop()

    st.success(f"✅ Pages: {len(pages)}")

    st.info(f"ICAOs Found: {len(st.session_state.all_icaos)}")
    st.success(f"Kept: {len(st.session_state.kept_icaos)}")
    st.warning(f"Removed: {len(st.session_state.removed_icaos)}")

    sections_present = {p[2] for p in pages}

    st.subheader("📌 Select Sections")

    selected_sections = []

    for sec in ["GEN", "ENR", "AD"]:
        if sec in sections_present:
            if st.checkbox(sec):
                selected_sections.append(sec)

    if not selected_sections:
        st.info("Select section to preview")
        st.stop()

    output_pdf = build_pdf(st.session_state.doc, pages, selected_sections)

    col1, col2 = st.columns([3, 1])

    # ✅ PREVIEW
    with col1:
        st.subheader("📄 Preview")

        preview_doc = fitz.open(stream=output_pdf.getvalue(), filetype="pdf")

        total = len(preview_doc)
        limit = st.session_state.preview_limit

        for i in range(min(limit, total)):
            pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(1, 1))
            st.image(pix.tobytes("png"), caption=f"Page {i+1}")

        preview_doc.close()

        if limit < total:
            if st.button("📂 Load More Pages"):
                st.session_state.preview_limit += 10
                st.rerun()

    # ✅ DOWNLOAD
    with col2:
        st.subheader("📥 Download")

        st.download_button(
            "Download PDF",
            data=output_pdf,
            file_name="Filtered_AIP.pdf",
            mime="application/pdf"
        )

    if st.session_state.removed_icaos:
        with st.expander("Removed ICAOs"):
            st.write(", ".join(sorted(st.session_state.removed_icaos)))
