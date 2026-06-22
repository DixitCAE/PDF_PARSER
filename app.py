import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter

# =============================
# MASTER CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data(ttl=300)
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df[0].dropna().astype(str).str.strip().str.upper())


# =============================
# HELPERS
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


def extract_section(text):
    t = text.upper()
    if re.search(r'\bGEN\s*\d', t): return "GEN"
    if re.search(r'\bENR\s*\d', t): return "ENR"
    if re.search(r'\bAD\s*\d', t): return "AD"
    return None


def should_remove(text):
    t = text.upper()
    rules = [
        r'GEN\s*0', r'GEN\s*2', r'GEN\s*3', r'GEN\s*4',
        r'ENR\s*0', r'ENR\s*2', r'ENR\s*6',
        r'AD\s*3'
    ]
    return any(re.search(r, t) for r in rules)


def extract_icao(page):
    blocks = page.get_text("blocks")
    header = " ".join([b[4] for b in blocks if b[1] < 150]).upper()

    patterns = [
        r'AD\s*[-\.]?\s*2\s*[-\.]?\s*([A-Z]{4})',
        r'([A-Z]{4})\s*AD\s*2'
    ]

    for p in patterns:
        m = re.search(p, header)
        if m:
            return m.group(1)

    return None


def detect_prefix(icaos):
    if not icaos: return None
    return Counter([c[:2] for c in icaos]).most_common(1)[0][0]


# =============================
# PROCESS PDF ✅ FINAL
# =============================
def process_pdf(file, date):

    doc = fitz.open(stream=file, filetype="pdf")
    allowed = load_master()

    temp = []

    # STEP 1: CLASSIFY FIRST
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()

        sec = extract_section(text)
        if not sec or should_remove(text):
            continue

        # ✅ date filter only GEN/ENR
        if sec in ["GEN", "ENR"]:
            if not match_date(text, date):
                continue

        temp.append((i, page, text, sec))

    # STEP 2: ICAO DETECTION
    raw_icaos = set()

    for _, page, _, sec in temp:
        if sec == "AD":
            code = extract_icao(page)
            if code:
                raw_icaos.add(code)

    prefix = detect_prefix(raw_icaos)
    all_icaos = {c for c in raw_icaos if prefix and c.startswith(prefix)}

    kept = {c for c in all_icaos if c in allowed}
    removed = all_icaos - kept

    # ✅ STEP 3: FINAL FILTER WITH DATE (AD ALSO)
    final = []

    for i, page, text, sec in temp:

        if sec == "AD":
            code = extract_icao(page)

            if not code:
                continue

            if prefix and not code.startswith(prefix):
                continue

            # ✅ ICAO must be valid
            if code not in kept:
                continue

            # ✅ NEW: date filter for AD pages
            if not match_date(text, date):
                continue

        final.append((i, text, sec))

    return doc, final, all_icaos, kept, removed


# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, sections):
    out = fitz.open()
    for i, _, sec in pages:
        if sec in sections:
            out.insert_pdf(doc, from_page=i, to_page=i)
    buf = BytesIO()
    out.save(buf)
    buf.seek(0)
    return buf


# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

file = st.file_uploader("Upload PDF", type=["pdf"])
date = st.date_input("Effective Date")

# track selection change
if "last_selection" not in st.session_state:
    st.session_state.last_selection = set()

if file:
    if st.button("🚀 Parse"):

        doc, pages, all_i, kept, removed = process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )

        st.session_state.update({
            "doc": doc,
            "pages": pages,
            "all_icaos": all_i,
            "kept": kept,
            "removed": removed,
            "processed": True,
            "preview_limit": 10,
            "last_selection": set()
        })

# =============================
# DISPLAY
# =============================
if st.session_state.get("processed"):

    pages = st.session_state.pages

    st.success(f"✅ Pages: {len(pages)}")
    st.info(f"ICAOs Found: {len(st.session_state.all_icaos)}")
    st.success(f"✅ Kept: {len(st.session_state.kept)}")
    st.warning(f"❌ Removed: {len(st.session_state.removed)}")

    present = {p[2] for p in pages}

    selected = set()
    for sec in ["GEN", "ENR", "AD"]:
        if sec in present:
            if st.checkbox(sec, key=sec):
                selected.add(sec)

    # ✅ RESET preview when selection changes
    if selected != st.session_state.last_selection:
        st.session_state.preview_limit = 10
        st.session_state.last_selection = selected

    if not selected:
        st.stop()

    pdf = build_pdf(st.session_state.doc, pages, selected)

    # ✅ PREVIEW
    st.subheader("📄 Preview")

    preview_doc = fitz.open(stream=pdf.getvalue(), filetype="pdf")

    total = len(preview_doc)
    limit = st.session_state.preview_limit

    for i in range(min(limit, total)):
        pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(1,1))
        st.image(pix.tobytes("png"), caption=f"Page {i+1}")

    if limit < total:
        if st.button("Load More"):
            st.session_state.preview_limit += 10
            st.rerun()

    st.download_button("Download PDF", pdf)

    if st.session_state.removed:
        with st.expander("Removed ICAOs"):
            st.write(", ".join(sorted(st.session_state.removed)))
