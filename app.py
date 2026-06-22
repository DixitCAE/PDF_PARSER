import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter

# =============================
# CONFIG
# =============================
st.set_page_config(layout="wide")

MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

# =============================
# LOAD MASTER
# =============================
@st.cache_data(ttl=300)
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df[0].dropna().astype(str).str.strip().str.upper())

# =============================
# HELPERS
# =============================
def match_date(text, date):
    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(date, "%d %b %Y")

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

    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()

        sec = extract_section(text)
        if not sec or should_remove(text):
            continue

        if sec in ["GEN", "ENR"]:
            if not match_date(text, date):
                continue

        temp.append((i, page, text, sec))

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

    final = []
    for i, page, text, sec in temp:

        if sec == "AD":
            code = extract_icao(page)
            if not code:
                continue
            if prefix and not code.startswith(prefix):
                continue
            if code not in kept:
                continue

            # ✅ SOFT DATE FILTER
            if any(m in text.upper() for m in ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]):
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
# SESSION STATE
# =============================
if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10

if "last_selection" not in st.session_state:
    st.session_state.last_selection = set()

# =============================
# UI HEADER
# =============================
st.markdown("## ✈️ Universal PDF Extractor")

file = st.file_uploader("Upload AIP PDF", type=["pdf"])
date = st.date_input("Effective Date")

# =============================
# RUN
# =============================
if file:
    if st.button("🚀 Parse"):

        doc, pages, all_i, kept, rem = process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )

        st.session_state.update({
            "doc": doc,
            "pages": pages,
            "all_icaos": all_i,
            "kept": kept,
            "removed": rem,
            "preview_limit": 10,
            "last_selection": set(),
            "processed": True
        })

# =============================
# DASHBOARD
# =============================
if st.session_state.get("processed"):

    pages = st.session_state.pages

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Pages", len(pages))
    col2.metric("ICAOs", len(st.session_state.all_icaos))
    col3.metric("Kept", len(st.session_state.kept))
    col4.metric("Removed", len(st.session_state.removed))

    present = {p[2] for p in pages}

    st.subheader("📌 Select Sections")

    selected = set()

    for sec in ["GEN", "ENR", "AD"]:
        if sec in present:
            if st.toggle(sec):
                selected.add(sec)

    if selected != st.session_state.last_selection:
        st.session_state.preview_limit = 10
        st.session_state.last_selection = selected

    if not selected:
        st.info("Select section to preview")
        st.stop()

    pdf = build_pdf(st.session_state.doc, pages, selected)

    colL, colR = st.columns([3,1])

    # =============================
    # PREVIEW
    # =============================
    with colL:
        st.subheader("📄 Preview")

        preview_doc = fitz.open(stream=pdf.getvalue(), filetype="pdf")

        total = len(preview_doc)
        limit = st.session_state.preview_limit

        st.caption(f"Showing {min(limit,total)} of {total} pages")

        for i in range(min(limit, total)):
            pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(1,1))
            st.image(pix.tobytes("png"))

        if limit < total:
            if st.button("⬇ Load More"):
                st.session_state.preview_limit += 10
                st.rerun()

    # =============================
    # SIDEBAR PANEL
    # =============================
    with colR:
        st.subheader("📥 Download")

        st.download_button("Download PDF", pdf)

        st.subheader("📊 ICAO Insight")

        st.write(f"✅ Kept: {len(st.session_state.kept)}")
        st.write(f"❌ Removed: {len(st.session_state.removed)}")

        if st.session_state.removed:
            with st.expander("Removed ICAOs"):
                for i in sorted(st.session_state.removed):
                    st.write(f"❌ {i}")

