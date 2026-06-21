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
    pid = pid.replace("GEN", "").replace("ENR", "").replace("AD", "")
    return pid.replace(" ", "").strip()


def extract_header_footer(page):
    blocks = page.get_text("blocks")
    h = page.rect.height

    text = ""
    for b in blocks:
        y0, y1 = b[1], b[3]

        if y1 < h * 0.25 or y0 > h * 0.75:
            text += b[4] + " "

    return text


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


# =============================
# ✅ CORE ENGINE (FINAL)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    selected_date = normalize_date(selected_date)

    matched_pages = []
    mapping = {}

    # =============================
    # STEP 1 — FIND CHECKLIST PAGES
    # =============================
    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text().upper() for k in CHECKLIST_KEYWORDS)
    ]

    # =============================
    # ✅ STEP 2 — ROBUST CHECKLIST PARSING
    # =============================
    for i in checklist_pages:

        text = doc[i].get_text("text")
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
    # STEP 3 — MAP PAGE IDs TO PDF
    # =============================
    page_map = {}

    for i, p in enumerate(doc):
        text = extract_header_footer(p)

        m = re.search(r'(?:GEN|ENR|AD)?\s*\d+\.\d+\-\d+', text)
        if m:
            pid = normalize_page_id(m.group())
            page_map[pid] = i

    # =============================
    # STEP 4 — MATCH USING CHECKLIST
    # =============================
    for pid, date in mapping.items():
        if date == selected_date and pid in page_map:
            matched_pages.append(page_map[pid])

    # =============================
    # 🔥 STEP 5 — CRITICAL RECOVERY FIX
    # =============================
    # If checklist missed pages → recover using full scan
    if len(matched_pages) < len(doc) * 0.3:   # dynamic threshold

        for i, p in enumerate(doc):
            full_text = p.get_text()

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
