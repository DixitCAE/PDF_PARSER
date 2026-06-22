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
    color: white;
}
.card {
    padding: 12px;
    border-radius: 12px;
    background: linear-gradient(145deg,#111c3a,#060b1f);
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    text-align:center;
}
.card h1 {font-size:28px;margin:0;}
.card h3 {font-size:14px;opacity:0.7;}
.preview-box {
    background:#0b132b;
    padding:10px;
    border-radius:10px;
}
.side-panel {
    background:#0b132b;
    padding:15px;
    border-radius:10px;
}
</style>
""", unsafe_allow_html=True)

MASTER_URL = "https://raw.githubusercontent.com/DixitCAE/PDF_PARSER/main/master_airport_list.csv"

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
    rules = [r'GEN\s*0',r'GEN\s*2',r'GEN\s*3',r'GEN\s*4',
             r'ENR\s*0',r'ENR\s*2',r'ENR\s*6',
             r'AD\s*3']
    return any(re.search(r,t) for r in rules)

def extract_icao(page):
    blocks = page.get_text("blocks")
    header = " ".join([b[4] for b in blocks if b[1]<150]).upper()

    patterns = [
        r'AD\s*[-\.]?\s*2\s*[-\.]?\s*([A-Z]{4})',
        r'([A-Z]{4})\s*AD\s*2'
    ]

    for p in patterns:
        m = re.search(p,header)
        if m:
            return m.group(1)
    return None

def detect_prefix(icaos):
    if not icaos:
        return None
    return Counter([c[:2] for c in icaos]).most_common(1)[0][0]

# =============================
# PROCESS
# =============================
def process_pdf(file, date):

    doc = fitz.open(stream=file, filetype="pdf")
    allowed = load_master()

    temp=[]
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()
        sec = extract_section(text)

        if not sec or should_remove(text):
            continue

        if sec in ["GEN","ENR"]:
            if not match_date(text,date):
                continue

        temp.append((i,page,text,sec))

    raw_icaos=set()
    for _,page,_,sec in temp:
        if sec=="AD":
            code=extract_icao(page)
            if code:
                raw_icaos.add(code)

    prefix=detect_prefix(raw_icaos)

    all_icaos={c for c in raw_icaos if prefix and c.startswith(prefix)}
    kept={c for c in all_icaos if c in allowed}
    removed=all_icaos-kept

    final=[]
    for i,page,text,sec in temp:

        if sec=="AD":
            code=extract_icao(page)
            if not code:
                continue
            if prefix and not code.startswith(prefix):
                continue
            if code not in kept:
                continue

            if any(m in text.upper() for m in ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]):
                if not match_date(text,date):
                    continue

        final.append((i,text,sec))

    return doc, final, all_icaos, kept, removed

# =============================
# BUILD
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
# SESSION
# =============================
if "processed" not in st.session_state:
    st.session_state.processed=False
if "preview_limit" not in st.session_state:
    st.session_state.preview_limit=10

# =============================
# UI
# =============================
st.title("✈️ Universal PDF Extractor")

file=st.file_uploader("Upload PDF",type=["pdf"])
date=st.date_input("Effective Date")

if file:
    if st.button("🚀 Parse"):
        doc,pages,all_i,kept,rem=process_pdf(
            file.read(),
            date.strftime("%d %b %Y")
        )
        st.session_state.update({
            "doc":doc,
            "pages":pages,
            "all_icaos":all_i,
            "kept":kept,
            "removed":rem,
            "processed":True
        })

if st.session_state.processed:

    pages = st.session_state.pages

    col1,col2,col3,col4=st.columns(4)

    def card(title,val):
        st.markdown(f"<div class='card'><h3>{title}</h3><h1>{val}</h1></div>",unsafe_allow_html=True)

    with col1: card("Pages",len(pages))
    with col2: card("ICAOs",len(st.session_state.all_icaos))
    with col3: card("Kept",len(st.session_state.kept))
    with col4: card("Removed",len(st.session_state.removed))

    present={p[2] for p in pages}

    selected=[]
    for sec in ["GEN","ENR","AD"]:
        if sec in present and st.toggle(sec):
            selected.append(sec)

    if not selected:
        st.stop()

    pdf=build_pdf(st.session_state.doc,pages,selected)

    colL,colR=st.columns([3,1])

    # PREVIEW
    with colL:
        st.subheader("Preview")

        zoom=st.slider("Zoom",0.8,3.0,1.2,0.1)

        preview_doc=fitz.open(stream=pdf.getvalue(),filetype="pdf")

        total=len(preview_doc)
        limit=st.session_state.preview_limit

        st.markdown(f"<div class='preview-box'>Showing {limit} of {total}</div>",unsafe_allow_html=True)

        for i in range(min(limit,total)):
            pix=preview_doc[i].get_pixmap(matrix=fitz.Matrix(zoom,zoom))
            st.image(pix.tobytes("png"), width="stretch")

        if limit<total:
            if st.button("Load More"):
                st.session_state.preview_limit+=10
                st.rerun()

    # SIDE PANEL
    with colR:
        st.markdown("<div class='side-panel'>",unsafe_allow_html=True)

        st.download_button("Download PDF",pdf)

        st.write(f"✅ Kept: {len(st.session_state.kept)}")
        st.write(f"❌ Removed: {len(st.session_state.removed)}")

        for i in sorted(st.session_state.removed):
            st.write(f"❌ {i}")

        st.markdown("</div>",unsafe_allow_html=True)
