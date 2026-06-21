import streamlit as st
import pymupdf
fitz = pymupdf

import re
from datetime import datetime
from io import BytesIO
from PIL import Image


# =============================
# HELPERS
# =============================

def normalize_date(date_str):
    date_str = re.sub(r"\s+", " ", date_str.upper()).strip()

    for fmt in ["%d %b %Y", "%d %b %y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%d %b %Y")
        except:
            pass

    return date_str


# ✅ UNIVERSAL DATE MATCHER (CRITICAL)
def match_date(text, selected_date):

    # normalize text
    text = re.sub(r"\s+", " ", text.upper())

    try:
        dt = datetime.strptime(selected_date, "%d %b %Y")
    except:
        return False

    patterns = [
        dt.strftime("%d %b %Y"),     # 09 JUL 2026
        dt.strftime("%-d %b %Y"),    # 9 JUL 2026
        dt.strftime("%d %b %y"),     # 09 JUL 26
        dt.strftime("%-d %b %y"),    # 9 JUL 26
    ]

    for p in patterns:
        if p in text:
            return True

    return False


# =============================
# CORE ENGINE (FINAL)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    selected_date = normalize_date(selected_date)

    matched_pages = []
    images = []

    # ✅ SCAN ALL PAGES (NO CHECKLIST / NO PAGE ID)
    for i, page in enumerate(doc):

        text = page.get_text("text")

        if match_date(text, selected_date):

            matched_pages.append(i)

            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            images.append(img)

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

    for p in matched_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

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

st.title("✈️ Universal AIP Page Extractor (Date-Based)")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")

if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("Analyzing all pages..."):

            date_str = selected_date.strftime("%d %b %Y")

            output_pdf, preview_images, count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if count == 0:
                st.warning("⚠️ No matching pages found")
            else:
                st.success(f"✅ Extracted {count} pages")

                st.subheader("📄 Preview")

                for i, img in enumerate(preview_images):
                    st.image(img, caption=f"Page {i+1}", use_container_width=True)

                st.download_button(
                    "📥 Download PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )
