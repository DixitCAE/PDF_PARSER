import streamlit as st
import fitz  # pymupdf
import re
from datetime import datetime
from io import BytesIO


# =============================
# ✅ FAST DATE MATCH
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())

    try:
        dt = datetime.strptime(selected_date, "%d %b %Y")
    except:
        return False

    day = str(dt.day)
    day2 = f"{dt.day:02}"
    month = dt.strftime("%b").upper()
    year_short = str(dt.year)[-2:]

    patterns = [
        f"{day}{month}{year_short}",
        f"{day2}{month}{year_short}",
    ]

    return any(p in text for p in patterns)


# =============================
# ✅ FAST CORE ENGINE
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    matched_pages = []

    # ✅ SINGLE PASS (FAST)
    for i in range(len(doc)):

        page = doc[i]

        # ✅ FAST TEXT EXTRACTION (blocks only)
        blocks = page.get_text("blocks")

        combined_text = ""
        for b in blocks:
            combined_text += b[4]

        if match_date(combined_text, selected_date):
            matched_pages.append(i)

    # ✅ SAFETY
    if not matched_pages:
        return None, [], 0

    # =============================
    # ✅ BUILD OUTPUT PDF
    # =============================
    output = fitz.open()

    for p in matched_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)
    output.close()
    doc.close()

    buffer.seek(0)

    return buffer, matched_pages, len(matched_pages)


# =============================
# ✅ UI (OPTIMIZED)
# =============================
st.set_page_config(layout="wide")

st.title("✈️ Fast AIP Extractor (High Performance)")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")


if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("Fast scanning..."):

            date_str = selected_date.strftime("%d %b %Y")

            output_pdf, matched_pages, count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if count == 0:
                st.warning("⚠️ No matching pages found")

            else:
                st.success(f"✅ Extracted {count} pages")

                # ✅ LIGHT PREVIEW (ONLY FIRST 5 PAGES)
                st.subheader("📄 Preview (first 5 pages only)")

                doc = fitz.open(stream=output_pdf.getvalue(), filetype="pdf")

                for i in range(min(5, count)):
                    pix = doc[i].get_pixmap(matrix=fitz.Matrix(1, 1))
                    st.image(pix.tobytes("png"))

                doc.close()

                # ✅ DOWNLOAD
                st.download_button(
                    "📥 Download PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )
