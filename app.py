import streamlit as st
import fitz
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from collections import Counter

st.set_page_config(layout="wide")

# =============================
# ✅ CSS (Premium + Animation)
# =============================
st.markdown("""
<style>

.stApp {
    background: radial-gradient(circle at top left,#0f1c3d,#02040a);
    color:white;
}

/* Cards */
.card {
    padding:10px;
    border-radius:10px;
    background:#111c3a;
    text-align:center;
}

/* Side panel */
.side-panel {
    background:#0b132b;
    padding:15px;
    border-radius:10px;
}

/* Aircraft animation */
.aircraft {
    position: relative;
    height: 20px;
    margin-top:10px;
}

.plane {
    position: absolute;
    font-size: 20px;
    animation: fly 2s linear forwards;
}

@keyframes fly {
    from { left: 0%; }
    to { left: 90%; }
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

# ✅ improved section detect
def extract_section(text):

    t = text.upper()

    if re.search(r'\bGEN\s*\d', t):
        return "GEN"

    if re.search(r'\bENR\s*\d', t):
        return "ENR"

    if re.search(r'\bAD\s*\d', t):
        return "AD"

    return None

# ✅ strict ICAO extraction
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

        if not sec:
            continue

        # ✅ DATE LOGIC FIX (header or footer)
        if sec in ["GEN","ENR","AD"]:
            if not match_date(text, date):
                continue

        temp.append((i,page,text,sec))

    # ✅ ICAO extraction only from AD
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

            if not code:
                continue

            if code not in kept:
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
# STATE INIT
# =============================
for k in ["pages","all_icaos","kept","removed","processed"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k=="pages" else set()

if "preview_limit" not in st.session_state:
    st.session_state.preview_limit = 10

# =============================
# UI HEADER
# =============================
st.title("✈️ AIP Trimmer")

file = st.file_uploader("Upload PDF", type=["pdf"])
date = st.date_input("Effective Date")

# =============================
# RUN
# =============================
if file:
    if st.button("🚀 Parse"):

        # ✅ aircraft animation
        plane_box = st.empty()

        plane_box.markdown('<div class="aircraft"><div class="plane">✈️</div></div>', unsafe_allow_html=True)

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

    # KPI
    c1,c2,c3,c4=st.columns(4)

    def card(t,v):
        st.markdown(f"<div class='card'><h3>{t}</h3><h1>{v}</h1></div>",unsafe_allow_html=True)

    with c1: card("Pages",len(pages))
    with c2: card("ICAOs",len(st.session_state.all_icaos))
    with c3: card("Kept",len(st.session_state.kept))
    with c4: card("Removed",len(st.session_state.removed))

    # ✅ section toggles fixed
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

    # ✅ PREVIEW WITH TRUE ZOOM
    with colL:

        st.subheader("Preview")

        zoom = st.slider("Zoom",0.5,2.5,1.0,0.1)

        base_width = 700

        preview_doc = fitz.open(stream=pdf.getvalue(),filetype="pdf")

        for i in range(min(10,len(preview_doc))):

            pix = preview_doc[i].get_pixmap(matrix=fitz.Matrix(2,2))

            st.image(pix.tobytes("png"),width=int(base_width*zoom))

    # ✅ RIGHT PANEL FIXED
    with colR:

        st.markdown("<div class='side-panel'>",unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        st.download_button("Download PDF", pdf)

        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown("### Removed ICAOs")

        for i in sorted(st.session_state.removed):
            st.write(i)

        st.markdown("</div>",unsafe_allow_html=True)
``
