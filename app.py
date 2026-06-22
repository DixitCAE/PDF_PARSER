import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO

# =============================
# ✅ CSV SOURCE
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
# DATE MATCH
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")

    patterns = [
        dt.strftime(f"{d}{m}{y}")
        for d in [str(dt.day), f"{dt.day:02}"]
        for m in [dt.strftime("%b").upper()]
        for y in [str(dt.year), str(dt.year)[-2:]]
    ]

    return any(p in text for p in patterns)


# =============================
# TEXT
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
        return "AD"

    return None


# =============================
# REMOVE RULES
# =============================
def should_remove(section):

    if not section:
        return True

    rules = [
        "GEN 0","GEN 2","GEN 3","GEN 4",
        "ENR 0","ENR 2","ENR 6",
        "AD 3"
    ]

    return any(section.startswith(r) for r in rules)


# =============================
# ✅ PROCESS PDF (FINAL FIXED)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    filtered_pages = []

    allowed_airports = load_master_airports()

    # ✅ STEP 1: FILTER PAGES (DATE + SECTION RULES)
    for i in range(len(doc)):

        text = extract_fast_text(doc[i])

        if not match_date(text, selected_date):
            continue

        sec = extract_section(text)

        if should_remove(sec):
            continue

        filtered_pages.append((i, text))

    # ✅ STEP 2: EXTRACT ICAOs ONLY FROM AD PAGES
    all_icaos = set()

    for _, text in filtered_pages:

        sec = extract_section(text)

        if sec == "AD":

            codes = re.findall(r'\b[A-Z]{4}\b', text.upper())

            # ✅ FILTER REAL ICAOs (avoid words)
            codes = [c for c in codes if c.isalpha()]

            all_icaos.update(codes)

    # ✅ STEP 3: MATCH WITH MASTER
    kept_icaos = {c for c in all_icaos if c in allowed_airports}
    removed_icaos = all_icaos - kept_icaos

    # ✅ STEP 4: FINAL PAGE FILTERING (AD only)
    cleaned_pages = []

    for page_num, text in filtered_pages:

        sec = extract_section(text)

        if sec == "AD":

            codes = re.findall(r'\b[A-Z]{4}\b', text.upper())

            if not any(c in kept_icaos for c in codes):
                continue

        cleaned_pages.append((page_num, text))

    return doc, cleaned_pages, all_icaos, kept_icaos, removed_icaos


# =============================
# BUILD PDF
# =============================
def build_filtered_pdf(doc, pages, selected_sections):

    final_pages = []

    for page_num, text in pages:

        sec = extract_section(text)

        if any(sec and sec.startswith(sel) for sel in selected_sections):
            final_pages.append(page_num)

    output = fitz.open()

    for p in sorted(set(final_pages)):
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)
    buffer.seek(0)

    return buffer, len(final_pages)


# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])
selected_date = st.date_input("Select Effective Date")


# =============================
# EXTRACT
# =============================
if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("Processing..."):

            doc, pages, all_icaos, kept, removed = process_pdf(
                uploaded_file.read(),
                selected_date.strftime("%d %b %Y")
            )

            st.session_state.doc = doc
            st.session_state.pages = pages
            st.session_state.all_icaos = all_icaos
            st.session_state.kept_icaos = kept
            st.session_state.removed_icaos = removed
            st.session_state.processed = True


# =============================
# DISPLAY
# =============================
if st.session_state.processed:

    pages = st.session_state.pages

    if not pages:
        st.warning("⚠️ No important sections found")
        st.stop()

    st.success(f"✅ Final Cleaned Pages: {len(pages)}")

    all_icaos = st.session_state.all_icaos
    kept = st.session_state.kept_icaos
    removed = st.session_state.removed_icaos

    col1, col2, col3 = st.columns(3)

    col1.info(f"📊 Total ICAOs (AD only): {len(all_icaos)}")
    col2.success(f"✅ Kept Airports: {len(kept)}")
    col3.warning(f"❌ Removed Airports: {len(removed)}")

    if removed:
        with st.expander("View Removed ICAOs"):
            st.write(", ".join(sorted(removed)))
