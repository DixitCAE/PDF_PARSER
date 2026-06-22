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
for key in ["processed","pages","doc","preview_limit",
            "all_icaos","kept_icaos","removed_icaos"]:
    if key not in st.session_state:
        if key == "pages":
            st.session_state[key] = []
        elif "icaos" in key:
            st.session_state[key] = set()
        elif key == "preview_limit":
            st.session_state[key] = 10
        else:
            st.session_state[key] = None if key=="doc" else False


# =============================
# COUNTRY PREFIX
# =============================
def get_country_prefix(filename):
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
# SECTION DETECT (FIXED)
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
# ICAO FROM HEADER ONLY
# =============================
def extract_icao_header(text):
    text = text.upper()

    match = re.search(r'AD[-\s]*\d*\.?[-\s]*([A-Z]{4})', text)
    return match.group(1) if match else None


# =============================
# PROCESS PDF
# =============================
def process_pdf(file_bytes, selected_date, filename):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    allowed_airports = load_master_airports()

    prefix = get_country_prefix(filename)

    filtered_pages = []

    # ✅ STEP 1: DATE + REMOVE RULES
    for i in range(len(doc)):

        text = extract_fast_text(doc[i])

        if not match_date(text, selected_date):
            continue

        if should_remove(text):
            continue

        section = extract_section(text)

        if section:
            filtered_pages.append((i, text, section))

    # ✅ STEP 2: ICAO FROM AD HEADER ONLY
    all_icaos = set()

    for _, text, section in filtered_pages:
        if section == "AD":
            icao = extract_icao_header(text)

            if icao and prefix and icao.startswith(prefix):
                all_icaos.add(icao)

    # ✅ STEP 3: COMPARE
    kept_icaos = {c for c in all_icaos if c in allowed_airports}
    removed_icaos = all_icaos - kept_icaos

    # ✅ STEP 4: FINAL PAGE FILTER
    cleaned_pages = []

    for p, text, section in filtered_pages:

        if section == "AD":
            icao = extract_icao_header(text)

            if not icao or icao not in kept_icaos:
                continue

        cleaned_pages.append((p, text, section))

    return doc, cleaned_pages, all_icaos, kept_icaos, removed_icaos


# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, selected_sections):

    output = fitz.open()

    for p, _, sec in pages:
        if sec in selected_sections:
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
date = st.date_input("Select Effective Date")


# =============================
# RUN
# =============================
if file:

    if st.button("🚀 Extract Pages"):

        with st.spinner("Processing..."):

            doc, pages, all_i, kept_i, rem_i = process_pdf(
                file.read(),
                date.strftime("%d %b %Y"),
                file.name
            )

            st.session_state.update({
                "doc": doc,
                "pages": pages,
                "all_icaos": all_i,
                "kept_icaos": kept_i,
                "removed_icaos": rem_i,
                "processed": True
            })


# =============================
# DISPLAY
# =============================
if st.session_state.processed:

    pages = st.session_state.pages

    st.success(f"✅ Final Cleaned Pages: {len(pages)}")

    st.info(f"📊 ICAOs Found: {len(st.session_state.all_icaos)}")
    st.success(f"✅ Kept: {len(st.session_state.kept_icaos)}")
    st.warning(f"❌ Removed: {len(st.session_state.removed_icaos)}")

    # ✅ SECTION FILTER (RESTORED)
    st.subheader("📌 Filter Sections")

    selected_sections = []

    for sec in ["GEN", "ENR", "AD"]:
        if any(s == sec for _,_,s in pages):
            if st.checkbox(sec):
                selected_sections.append(sec)

    if not selected_sections:
        st.info("Select a section to preview")
        st.stop()

    pdf = build_pdf(st.session_state.doc, pages, selected_sections)

    st.download_button("Download PDF", pdf)

    if st.session_state.removed_icaos:
        with st.expander("Removed ICAOs"):
            st.write(", ".join(sorted(st.session_state.removed_icaos)))
