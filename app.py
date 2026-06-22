import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO

# =============================
# CSV SOURCE
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data(ttl=300)
def load_master_airports():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df.iloc[:, 0].dropna().astype(str).str.strip().str.upper())


# =============================
# SESSION STATE
# =============================
for key in ["processed","pages","doc","preview_limit","all_icaos","kept_icaos","removed_icaos"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key=="pages" else set() if "icaos" in key else False if key=="processed" else None

if st.session_state.preview_limit is None:
    st.session_state.preview_limit = 10


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
# TEXT EXTRACTION
# =============================
def extract_fast_text(page):
    return " ".join([b[4] for b in page.get_text("blocks")])


# =============================
# SECTION DETECT
# =============================
def extract_section(text):

    text = text.upper()

    if "AD" in text:
        return "AD"

    m = re.search(r'(GEN\s*\d+)|(ENR\s*\d+)', text)
    if m:
        return m.group()

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
# ✅ ROBUST ICAO EXTRACTION
# =============================
def extract_icao(text):

    text = text.upper()

    patterns = [
        r'AD\s*2(?:\.\d+)?\s*([A-Z]{4})',
        r'([A-Z]{4})\s*AD\s*2'
    ]

    for p in patterns:
        match = re.search(p, text)
        if match:
            return match.group(1)

    return None


# =============================
# PROCESS PDF
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    filtered_pages = []

    allowed_airports = load_master_airports()

    # ✅ STEP 1: DATE + SECTION FILTER
    for i in range(len(doc)):

        text = extract_fast_text(doc[i])

        if not match_date(text, selected_date):
            continue

        sec = extract_section(text)

        if should_remove(sec):
            continue

        filtered_pages.append((i, text))

    # ✅ STEP 2: EXTRACT ICAOS ONLY FROM AD
    all_icaos = set()

    for _, text in filtered_pages:

        if "AD" in text:
            icao = extract_icao(text)
            if icao:
                all_icaos.add(icao)

    # ✅ STEP 3: COMPARE
    kept_icaos = {c for c in all_icaos if c in allowed_airports}
    removed_icaos = all_icaos - kept_icaos

    # ✅ STEP 4: FINAL PAGE FILTER
    cleaned_pages = []

    for page_num, text in filtered_pages:

        sec = extract_section(text)

        if sec == "AD":

            icao = extract_icao(text)

            if not icao or icao not in kept_icaos:
                continue

        cleaned_pages.append((page_num, text))

    return doc, cleaned_pages, all_icaos, kept_icaos, removed_icaos


# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])
selected_date = st.date_input("Select Effective Date")


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


if st.session_state.processed:

    pages = st.session_state.pages

    if not pages:
        st.warning("⚠️ No important sections found")
        st.stop()

    st.success(f"✅ Final Cleaned Pages: {len(pages)}")

    st.info(f"📊 Total ICAOs (AD robust): {len(st.session_state.all_icaos)}")
    st.success(f"✅ Kept Airports: {len(st.session_state.kept_icaos)}")
    st.warning(f"❌ Removed Airports: {len(st.session_state.removed_icaos)}")

    if st.session_state.removed_icaos:
        with st.expander("View Removed ICAOs"):
            st.write(", ".join(sorted(st.session_state.removed_icaos)))
