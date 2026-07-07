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
st.markdown("""
<style>

/* Background */
.stApp {
    background: radial-gradient(circle at top left,#0f1c3d,#02040a);
    color:white;
}

/* KPI Cards */
.card {
    padding:12px;
    border-radius:12px;
    background:linear-gradient(145deg,#111c3a,#060b1f);
    box-shadow:0 4px 12px rgba(0,0,0,0.4);
    text-align:center;
    transition:0.2s;
}
.card:hover {transform:translateY(-3px);}
.card h1 {font-size:26px;margin:0;}
.card h3 {font-size:14px;opacity:0.7;margin-bottom:4px;}

/* Side Panel */
.side-panel {
    background:#0b132b;
    padding:15px;
    border-radius:10px;
}

/* ✈ Aircraft animation */
.aircraft {
    position: relative;
    height: 30px;
}
.plane {
    position: absolute;
    font-size: 22px;
    animation: fly 2s linear infinite;
}
@keyframes fly {
    from {left:0%;}
    to {left:90%;}
}

</style>
""", unsafe_allow_html=True)

# =============================
# MASTER CSV
# =============================
MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df[0].dropna().astype(str).str.strip().str.upper())

# =============================
# HELPERS
# =============================
def match_date(text, selected_date):
    text_clean = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")

    patterns = [
        f"{d}{dt.strftime('%b').upper()}{y}"
        for d in [str(dt.day), f"{dt.day:02}"]
        for y in [str(dt.year), str(dt.year)[-2:]]
    ]

    return any(p in text_clean for p in patterns)

def should_remove_section(text):

    t = text.upper()

    rules = [
        r'\bGEN\s*0',
        r'\bGEN\s*1',
        r'\bGEN\s*2',
        r'\bGEN\s*3',
        r'\bGEN\s*4',
        r'\bENR\s*0',
        r'\bENR\s*2',
        r'\bENR\s*6'
    ]

    return any(re.search(rule, t) for rule in rules)

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

    temp=[]

    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()

        sec = extract_section(text)

if not sec:
    continue

# ✅ HARDCODED REMOVAL RULES
if should_remove_section(text):
    continue

# ✅ DATE FILTER
if not match_date(text, date):
    continue

        temp.append((i,page,text,sec))

    raw=set()

    for _,page,_,sec in temp:
        if sec=="AD":
            code=extract_icao(page)
            if code:
                raw.add(code)

    prefix=detect_prefix(raw)

    all_icaos={c for c in raw if prefix and c.startswith(prefix)}
    kept={c for c in all_icaos if c in allowed}
    removed=all_icaos-kept

    final=[]
    for i,page,text,sec in temp:
        if sec=="AD":
            code=extract_icao(page)
            if not code or code not in kept:
                continue
        final.append((i,text,sec))

    return doc, final, all_icaos, kept, removed

# =============================
# BUILD PDF
# =============================
def build_pdf(doc,pages,sections):
    out=fitz.open()
    for i,_,sec in pages:
        if sec in sections:
            out.insert_pdf(doc,from_page=i,to_page=i)
    buf=BytesIO()
    out.save(buf)
    buf.seek(0)
    return buf

# =============================
# STATE INIT
# =============================
for k in ["pages","all_icaos","kept","removed"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k=="pages" else set()

if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10

if "processed" not in st.session_state:
    st.session_state.processed = False

# =============================
# UI
# =============================
st.title("✈️ AIP Trimmer")

file = st.file_uploader("Upload PDF", type=["pdf"])
date = st.date_input("Effective Date")

# =============================
# RUN
# =============================
if file:
    if st.button("🚀 Parse"):

        st.session_state.preview_limit = 10

        # ✅ Aircraft animation
        plane_box = st.empty()
        plane_box.markdown("""
        <div class="aircraft">
            <div class="plane">✈️</div>
        </div>
        """, unsafe_allow_html=True)

        doc,pages,all_i,kept,removed = process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )

        plane_box.empty()

        st.session_state.update({
            "doc":doc,
            "pages":pages,
            "all_icaos":all_i,
            "kept":kept,
            "removed":removed,
            "processed":True
        })

# =============================
# DISPLAY
# =============================
if st.session_state.processed:

    pages = st.session_state.pages

    # ✅ KPI CARDS
    def card(t,v):
        st.markdown(f"""
        <div class='card'>
            <h3>{t}</h3>
            <h1>{v}</h1>
        </div>
        """, unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)

    with c1: card("Pages",len(pages))
    with c2: card("ICAOs",len(st.session_state.all_icaos))
    with c3: card("Kept",len(st.session_state.kept))
    with c4: card("Removed",len(st.session_state.removed))

    present = {p[2] for p in pages}

    selected=[]
    for sec in ["GEN","ENR","AD"]:
        if sec in present:
            if st.toggle(sec):
                selected.append(sec)

    if not selected:
        st.stop()

    pdf = build_pdf(st.session_state.doc,pages,selected)

    colL,colR = st.columns([3,1])

    # ✅ PREVIEW
    with colL:
        st.subheader("Preview")

        zoom = st.slider("Zoom",0.5,2.5,1.0,0.1)

        preview_doc = fitz.open(stream=pdf.getvalue(), filetype="pdf")

        total = len(preview_doc)
        limit = st.session_state.preview_limit

        for i in range(min(limit, total)):
            pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(2,2))
            st.image(pix.tobytes("png"), width=int(700 * zoom))

        # ✅ LOAD MORE FIX
        if limit < total:
            if st.button("⬇ Load More Pages"):
                st.session_state.preview_limit += 10
                st.rerun()

    # ✅ SIDE PANEL
    with colR:
        st.markdown("<div class='side-panel'>", unsafe_allow_html=True)

        st.download_button("Download PDF", pdf)

        st.markdown("### Removed ICAOs")
        for i in sorted(st.session_state.removed):
            st.write(i)

        st.markdown("</div>", unsafe_allow_html=True)
