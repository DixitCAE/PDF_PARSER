import streamlit as st
import fitz  # pymupdf
import re
from datetime import datetime
from io import BytesIO


# =============================
# ✅ DATE MATCHER (FINAL FIXED)
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())

    try:
        dt = datetime.strptime(selected_date, "%d %b %Y")
    except:
        return False

    day1 = str(dt.day)
    day2 = f"{dt.day:02}"
    month = dt.strftime("%b").upper()
    year_full = str(dt.year)
    year_short = year_full[-2:]

    patterns = [
        # ✅ FULL YEAR
        f"{day1}{month}{year_full}",
        f"{day2}{month}{year_full}",
        f"{month}{day1}{year_full}",
        f"{month}{day2}{year_full}",

        # ✅ SHORT YEAR
        f"{day1}{month}{year_short}",
        f"{day2}{month}{year_short}",
        f"{month}{day1}{year_short}",
        f"{month}{day2}{year_short}",
    ]

    return any(p in text for p in patterns)


# =============================
# ✅ FAST TEXT EXTRACTION
# =============================
def extract_fast_text(page):

    blocks = page.get_text("blocks")

    combined = ""
    for b in blocks:
        combined += b[4]

    return combined


# =============================
# ✅ CORE ENGINE (FAST + SAFE)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    matched_pages = []

    for i in range(len(doc)):

        page = doc[i]
        text = extract_fast_text(page)

        if match_date(text, selected_date):
            matched_pages.append(i)

    if not matched_pages:
        return None, [], 0

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
# ✅ UI (UPDATED)
# =============================
st.set_page_config(layout="wide")

# ✅ HEADER CHANGE
st.title("✈️ Universal PDF Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")


if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        # ✅ UPDATED SPINNER
        with st.spinner("🛫 Processing the request..."):

            date_str = selected_date.strftime("%d %b %Y")

            output_pdf, matched_pages, count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if count == 0:
                st.warning("⚠️ No matching pages found")

            else:
                st.success(f"✅ Extracted {count} pages")

                # ✅ SIDE-BY-SIDE LAYOUT
                col_preview, col_download = st.columns([3, 1])

                # =============================
                # ✅ PREVIEW
                # =============================
                with col_preview:

                    st.subheader("📄 Preview (first 5 pages)")

                    doc_preview = fitz.open(
                        stream=output_pdf.getvalue(),
                        filetype="pdf"
                    )

                    for i in range(min(5, count)):
                        pix = doc_preview[i].get_pixmap(matrix=fitz.Matrix(1, 1))
                        st.image(pix.tobytes("png"))

                    doc_preview.close()

                # =============================
                # ✅ DOWNLOAD (TOP RIGHT)
                # =============================
                with col_download:

                    st.subheader("📥 Download")

                    st.download_button(
                        "Download PDF",
                        data=output_pdf,
                        file_name=f"AIP_{date_str}.pdf",
                        mime="application/pdf"
                    )
