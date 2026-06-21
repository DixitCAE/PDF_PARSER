import streamlit as st
import pymupdf
fitz = pymupdf

import re
from datetime import datetime
from io import BytesIO
from PIL import Image


# =============================
# CONFIG
# =============================
CHECKLIST_KEYWORDS = [
    "CHECKLIST OF AIP PAGES",
    "CHECKLIST OF EAIP PAGES",
    "LISTE RECAPITULATIVE DES PAGES"
]


# =============================
# HELPERS
# =============================

def normalize_date(date_str):
    date_str = re.sub(r"\s+", " ", date_str.upper()).strip()

    for fmt in ["%d %b %y", "%d %b %Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d %b %Y")
        except:
            pass

    return date_str


def normalize_page_id(pid):
    pid = pid.upper()

    # remove section labels
    pid = pid.replace("GEN", "")
    pid = pid.replace("ENR", "")
    pid = pid.replace("AD", "")

    return re.sub(r"\s+", "", pid)


# ✅ STRONG DATE MATCH
def is_date_present(text, target_date):

    text = re.sub(r"\s+", " ", text.upper())

    try:
        dt = datetime.strptime(target_date, "%d %b %Y")
    except:
        return False

    patterns = [
        dt.strftime("%d %b %Y"),
        dt.strftime("%-d %b %Y"),
        dt.strftime("%d %b %y"),
        dt.strftime("%-d %b %y"),
    ]

    return any(p in text for p in patterns)


# ✅ ✅ ✅ FINAL PAGE ID EXTRACTOR (CORE FIX)
def extract_page_id(page):

    text = page.get_text("text").upper()

    patterns = [
        r'\b\d+\.\d+\-\d+\b',                 # 3.2-1
        r'(?:GEN|ENR)\s*\d+\.\d+\-\d+',       # GEN 3.2-1, ENR 3.2-1
        r'AD\s*\d+\s*[A-Z0-9]+\-\d+',         # AD 2 VTBS-1 ✅
        r'AD\s*\d+\.[A-Z0-9\-]+'              # AD 2.RCTP-1
    ]

    for ptn in patterns:
        m = re.search(ptn, text)
        if m:
            return normalize_page_id(m.group())

    return None


# =============================
# ✅ CORE ENGINE (FINAL)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    selected_date = normalize_date(selected_date)

    matched_pages = []
    mapping = {}

    # =============================
    # STEP 1 — CHECKLIST PARSING
    # =============================
    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text().upper() for k in CHECKLIST_KEYWORDS)
    ]

    for i in checklist_pages:

        text = doc[i].get_text()

        tokens = re.split(r"\s+", text)

        for j in range(len(tokens) - 3):

            chunk = " ".join(tokens[j:j+4])

            m = re.search(
                r'([A-Z]*\s*\d+\.\d+\-\d+)\s*(\d{1,2}\s[A-Z]{3}\s\d{2,4})',
                chunk
            )

            if m:
                pid = normalize_page_id(m.group(1))
                date = normalize_date(m.group(2))

                mapping[pid] = date

    # =============================
    # STEP 2 — PAGE MAP (FIXED)
    # =============================
    page_map = {}

    for i, page in enumerate(doc):

        pid = extract_page_id(page)

        if pid:
            page_map[pid] = i

    # =============================
    # STEP 3 — CHECKLIST MATCH
    # =============================
    for pid, date in mapping.items():

        if date == selected_date and pid in page_map:
            matched_pages.append(page_map[pid])

    # =============================
    # ✅ CRITICAL FALLBACK (FINAL SAFETY)
    # =============================
    if len(matched_pages) < 50:

        for i, page in enumerate(doc):

            full_text = page.get_text()

            if is_date_present(full_text, selected_date):
                matched_pages.append(i)

    matched_pages = sorted(set(matched_pages))

    # =============================
    # SAFETY
    # =============================
    if len(matched_pages) == 0:
        return None, None, 0

    # =============================
    # CREATE OUTPUT PDF
    # =============================
    output = fitz.open()
    images = []

    for p in matched_pages:

        output.insert_pdf(doc, from_page=p, to_page=p)

        pix = doc[p].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        images.append(img)

    buffer = BytesIO()
    output.save(buffer)

    output.close()
    doc.close()

    buffer.seek(0)

    return buffer, images, len(matched_pages)


# =============================
# UI
# =============================
st.set_page_config(layout="wide")

st.title("✈️ AIP Effective Page Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")

if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Parse and Extract"):

        with st.spinner("Processing PDF..."):

            date_str = selected_date.strftime("%d %b %Y")

            output_pdf, preview_images, count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if count == 0:
                st.warning("⚠️ No matching pages found")
            else:
                st.success(f"✅ Found {count} pages")

                st.subheader("📄 Page Preview")

                for i, img in enumerate(preview_images):
                    st.image(img, caption=f"Page {i+1}", use_container_width=True)

                st.download_button(
                    label="📥 Download PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )
