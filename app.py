import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter

st.set_page_config(layout="wide")

# =============================
# ✅ PREMIUM UI CSS
# =============================
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(135deg, #0f172a, #111827);
        color: white;
    }
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3, h4, h5, h6, p, label, div {
        color: white !important;
    }
    .stButton > button {
        background: linear-gradient(90deg, #2563eb, #1d4ed8);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
    }
    .stDownloadButton > button {
        background: linear-gradient(90deg, #059669, #047857);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
    }
    .card {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        padding: 1rem;
        border-radius: 14px;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =============================
# MASTER CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df[0].dropna().astype(str).str.strip().str.upper())

# =============================
# HARD-CODED SECTION REMOVAL
# =============================
HARD_REMOVE_SECTIONS = {
    "GEN1", "GEN2", "GEN3", "GEN4", "GEN5",
    "ENR2", "ENR5", "ENR6"
}

# =============================
# HELPERS
# =============================
def match_date(text, selected_date):
    text_clean = re.sub(r'[\s\.\-\:/\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")
    patterns = [
        f"{d}{dt.strftime('%b').upper()}{y}"
        for d in [str(dt.day), f"{dt.day:02}"]
        for y in [str(dt.year), str(dt.year)[-2:]]
    ]
    return any(p in text_clean for p in patterns)

def extract_section(text):
    t = text.upper()
    m = re.search(r'\b(GEN|ENR|AD)\s*([1-9])\b', t)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None

def is_hard_removed_section(section):
    return section in HARD_REMOVE_SECTIONS

def extract_icao(page):
    blocks = page.get_text("blocks")
    header_text = " ".join([b[4] for b in blocks if b[1] < 120]).upper()
    patterns = [
        r'AD\s*[-\.]?\s*2\s*[-\.]?\s*([A-Z]{4})',
        r'([A-Z]{4})\s*AD\s*2'
    ]
    for p in patterns:
        m = re.search(p, header_text)
        if m:
            return m.group(1)
    return None

def detect_prefix(icaos):
    if not icaos:
        return None
    return Counter([c[:2] for c in icaos]).most_common(1)[0][0]

# =============================
# PROCESS PDF
# =============================
def process_pdf(file, date):
    doc = fitz.open(stream=file, filetype="pdf")
    allowed = load_master()

    temp = []
    skipped_hard_removed = []

    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()
        sec = extract_section(text)
        if not sec:
            continue

        if is_hard_removed_section(sec):
            skipped_hard_removed.append((i, text, sec))
            continue

        if not match_date(text, date):
            continue

        temp.append((i, page, text, sec))

    raw = set()
    for _, page, _, sec in temp:
        if sec == "AD":
            code = extract_icao(page)
            if code:
                raw.add(code)

    prefix = detect_prefix(raw)
    all_icaos = {c for c in raw if prefix and c.startswith(prefix)}
    kept = {c for c in all_icaos if c in allowed}
    removed = all_icaos - kept

    final = []
    for i, page, text, sec in temp:
        if sec == "AD":
            code = extract_icao(page)
            if not code or code not in kept:
                continue
        final.append((i, text, sec))

    return doc, final, all_icaos, kept, removed, skipped_hard_removed

# =============================
# BUILD PDF
# =============================
def build_pdf(doc, pages, sections=None):
    out = fitz.open()
    if sections is None:
        sections = set()

    for i, _, sec in pages:
        if not sections or sec in sections:
            out.insert_pdf(doc, from_page=i, to_page=i)

    buf = BytesIO()
    out.save(buf)
    buf.seek(0)
    return buf

# =============================
# STATE INIT
# =============================
for k in ["pages", "all_icaos", "kept", "removed", "hard_removed"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k == "pages" else set()

if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10

if "processed" not in st.session_state:
    st.session_state.processed = False

# =============================
# UI
# =============================
st.title("✈️ AIP Trimmer")
st.caption("Hard removes GEN1-5 and ENR2/5/6 regardless of date.")

col1, col2 = st.columns(2)
with col1:
    file = st.file_uploader("Upload PDF", type=["pdf"])
with col2:
    date = st.date_input("Effective Date")

# =============================
# RUN
# =============================
if file:
    if st.button("🚀 Parse"):
        st.session_state.preview_limit = 10
        plane_box = st.empty()
        plane_box.markdown(
            """
            <div class="card">
                <h3>Parsing in progress...</h3>
                <p>Trimming AIP document with hard-coded section exclusions.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        doc, final, all_icaos, kept, removed, hard_removed = process_pdf(file, date.strftime("%d %b %Y"))

        st.session_state.pages = final
        st.session_state.all_icaos = all_icaos
        st.session_state.kept = kept
        st.session_state.removed = removed
        st.session_state.hard_removed = {sec for _, _, sec in hard_removed}
        st.session_state.processed = True

        plane_box.empty()

        st.success("PDF parsed successfully.")

        st.markdown("### Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Kept AD ICAOs", len(kept))
        c2.metric("Removed ICAOs", len(removed))
        c3.metric("Hard-Removed Sections", len(st.session_state.hard_removed))
        c4.metric("Output Pages", len(final))

        st.markdown("### Hard-Removed Sections")
        st.write(", ".join(sorted(HARD_REMOVE_SECTIONS)))

        st.markdown("### ICAO Preview")
        if all_icaos:
            st.write(sorted(all_icaos))
        else:
            st.info("No ICAO codes found.")

        if final:
            pdf_buf = build_pdf(doc, final, sections={"AD"})
            st.download_button(
                "⬇️ Download Trimmed PDF",
                data=pdf_buf,
                file_name="trimmed_aip.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("No pages left after trimming.")

        st.markdown("### Removed ICAOs")
        if removed:
            st.write(sorted(removed))

        st.markdown("### Kept ICAOs")
        if kept:
            st.write(sorted(kept))
