import streamlit as st
import pymupdf
fitz = pymupdf

import re
from datetime import datetime
from io import BytesIO
from PIL import Image


# =============================
# ✅ ADVANCED DATE MATCHER
# =============================
def match_date(text, selected_date):

    text = text.upper()

    # remove all spaces, tabs, line breaks
    text_compact = re.sub(r'[\s\.\-\:\,\/]', '', text)

    try:
        dt = datetime.strptime(selected_date, "%d %b %Y")
    except:
        return False

    day = str(dt.day)
    day2 = f"{dt.day:02}"
    month = dt.strftime("%b").upper()
    year_full = str(dt.year)
    year_short = str(dt.year)[-2:]

    # ✅ build multiple flexible patterns
    patterns = [
        f"{day}{month}{year_full}",
        f"{day2}{month}{year_full}",
        f"{day}{month}{year_short}",
        f"{day2}{month}{year_short}",

        f"{month}{day}{year_full}",
        f"{month}{day2}{year_full}",

        f"{day}{month}",
        f"{month}{day}",

        f"{day2}{month}",
        f"{month}{day2}",
    ]

    for p in patterns:
        if p in text_compact:
            return True

    return False


# =============================
# ✅ CORE ENGINE
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    matched_pages = []
    images = []

    for i, page in enumerate(doc):

        text = page.get_text("text")

        if match_date(text, selected_date):

            matched_pages.append(i)

            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            images.append(img)

    matched_pages = sorted(set(matched_pages))

    if len(matched_pages) == 0:
        return None, None, 0

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
# ✅ UI
# =============================
st.set_page_config(layout="wide")

st.title("✈️ Universal AIP Date Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")

if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("Scanning all pages..."):

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
