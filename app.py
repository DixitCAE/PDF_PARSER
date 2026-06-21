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


def clean_text(text):
    return re.sub(r"\s+", " ", text.upper())


# ✅ STRONG DATE MATCHER (FINAL)
def match_date_in_text(text, target_date):

    text = clean_text(text)

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

    for p in patterns:
        if p in text:
            return True

    return False


# =============================
# CORE ENGINE (FINAL-STABLE)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    selected_date = normalize_date(selected_date)

    matched_pages = []
    images = []

    # ✅ PRIMARY METHOD (ALWAYS WORKS)
    for i, page in enumerate(doc):

        text = page.get_text()

        # 🔥 KEY FIX → no header assumption
        if match_date_in_text(text, selected_date):

            matched_pages.append(i)

            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            images.append(img)

    # =============================
    # SAFETY
    # =============================
    if len(matched_pages) == 0:
        return None, None, 0

    # =============================
    # CREATE PDF
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

st.title("✈️ Universal AIP Page Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")

if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Parse and Extract"):

        with st.spinner("Processing..."):

            date_str = selected_date.strftime("%d %b %Y")

            output_pdf, preview_images, count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if count == 0:
                st.warning("⚠️ No matching pages found")
            else:
                st.success(f"✅ Extracted {count} pages")

                st.subheader("📄 Page Preview")

                for i, img in enumerate(preview_images):
                    st.image(img, caption=f"Page {i+1}", use_container_width=True)

                # ✅ DOWNLOAD BUTTON
                st.download_button(
                    label="📥 Download Filtered PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )

