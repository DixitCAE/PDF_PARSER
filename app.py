import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter

st.set_page_config(layout="wide")

# =============================
# ✅ CSS
# =============================
st.markdown("""
<style>
.stApp {
    background: radial-gradient(circle at top left,#0f1c3d,#02040a);
    color:white;
}
.card {
    padding:10px;
    border-radius:10px;
    background:#111c3a;
    text-align:center;
}
.preview-box {
    background:#0b132b;
    padding:10px;
    border-radius:8px;
}
.side-panel {
    background:#0b132b;
    padding:15px;
    border-radius:10px;
}
</style>
""", unsafe_allow_html=True)

MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

@st.cache_data
def load_master():
    df = pd.read_csv(MASTER_URL, header=None)
    return set(df[0].dropna().str.strip().str.upper())

# =============================
# HELPERS
# =============================
def match_date(text, date):
    text = re.sub(r'[^\w]', '', text.upper())
    dt = datetime.strptime(date, "%d %b %Y")
    patterns = [
        f"{d}{dt.strftime('%b').upper()}{y}"
        for d in [str(dt.day), f"{dt.day:02}"]
        for y in [str(dt.year), str(dt.year)[-2:]]
    ]
    return any(p in text for p in patterns)

def extract_section(text):
    t = text.upper()
    if "GEN" in t: return "GEN"
    if "ENR" in t: return "ENR"
    if "AD" in t: return "AD"
    return None

def should_remove(text):
    return False

def extract_icao(page):
    blocks = page.get_text("blocks")
    header = " ".join([b[4] for b in blocks if b[1]<150]).upper()
    m = re.search(r'([A-Z]{4})', header)
    return m.group(1) if m else None

def detect_prefix(icaos):
    return Counter([c[:2] for c in icaos]).most_common(1)[0][0] if icaos else None

# =============================
# PROCESS
# =============================
def process_pdf(file,date):

    doc = fitz.open(stream=file)
    allowed = load_master()

    temp=[]
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()
        sec = extract_section(text)

        if not sec:
            continue

        if sec in ["GEN","ENR"]:
            if not match_date(text,date):
                continue

        temp.append((i,page,text,sec))

    raw=set()
    for _,p,_,s in temp:
        if s=="AD":
            code=extract_icao(p)
            if code:
                raw.add(code)

    prefix=detect_prefix(raw)
    kept={c for c in raw if c in allowed}
    removed=raw-kept

    final=[]
    for i,p,t,s in temp:
        if s=="AD":
            c=extract_icao(p)
            if not c or c not in kept:
                continue
        final.append((i,t,s))

    return doc,final,raw,kept,removed

# =============================
# BUILD
# =============================
def build_pdf(doc,pages,sections):
    out=fitz.open()
    for i,_,s in pages:
        if s in sections:
            out.insert_pdf(doc,from_page=i,to_page=i)
    buf=BytesIO()
    out.save(buf)
    buf.seek(0)
    return buf

# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

file=st.file_uploader("Upload PDF")
date=st.date_input("Date")

if file and st.button("Parse"):

    doc,pages,all_i,kept,removed = process_pdf(
        file.read(),
        date.strftime("%d %b %Y")
    )

    st.session_state.update({
        "doc":doc,
        "pages":pages,
        "all":all_i,
        "kept":kept,
        "removed":removed,
        "limit":10
    })

if "pages" in st.session_state:

    pages=st.session_state.pages

    c1,c2,c3,c4=st.columns(4)

    with c1: st.markdown(f"<div class='card'><h3>Pages</h3><h1>{len(pages)}</h1></div>",unsafe_allow_html=True)
    with c2: st.markdown(f"<div class='card'><h3>ICAOs</h3><h1>{len(st.session_state.all)}</h1></div>",unsafe_allow_html=True)
    with c3: st.markdown(f"<div class='card'><h3>Kept</h3><h1>{len(st.session_state.kept)}</h1></div>",unsafe_allow_html=True)
    with c4: st.markdown(f"<div class='card'><h3>Removed</h3><h1>{len(st.session_state.removed)}</h1></div>",unsafe_allow_html=True)

    pdf=build_pdf(st.session_state.doc,pages,["AD","GEN","ENR"])

    colL,colR=st.columns([3,1])

    with colL:
        st.subheader("Preview")

        # ✅ TRUE ZOOM
        zoom = st.slider("Zoom",0.5,2.5,1.0,0.1)

        base_width = 700  # ✅ control real size

        preview_doc=fitz.open(stream=pdf.getvalue())

        for i in range(min(st.session_state.limit,len(preview_doc))):

            page=preview_doc[i]

            # ✅ HIGH RES ALWAYS
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2))

            # ✅ TRUE SIZE SCALE
            width=int(base_width * zoom)

            st.image(pix.tobytes("png"), width=width)

        if st.session_state.limit < len(preview_doc):
            if st.button("Load More"):
                st.session_state.limit+=10
                st.rerun()

    with colR:
        st.download_button("Download PDF",pdf)

        st.write("Removed ICAOs")
        for r in st.session_state.removed:
            st.write(r)
