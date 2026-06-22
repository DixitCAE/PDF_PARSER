import streamlit as st
import fitz
import re
from datetime import datetime
from io import BytesIO


# =============================
# ✅ DATE MATCHER
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())

    dt = datetime.strptime(selected_date, "%d %b %Y")

    day1 = str(dt.day)
    day2 = f"{dt.day:02}"
    month = dt.strftime("%b").upper()
    year_full = str(dt.year)
    year_short = year_full[-2:]

    patterns = [
        # FULL YEAR
        f"{day1}{month}{year_full}",
        f"{day2}{month}{year_full}",
        f"{month}{day1}{year_full}",
        f"{month}{day2}{year_full}",

        # SHORT YEAR
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
    return " ".join([b[4] for b in blocks])


# =============================
# ✅ SECTION EXTRACTION (FIXED)
# =============================
def extract_section(text):

    text = text.upper()

    # ✅ GEN / ENR (granular)
    m = re.search(r'(GEN\s*\d+(\.\d+)?)|(ENR\s*\d+(\.\d+)?)', text)
    if m:
        return re.sub(r"\s+", " ", m.group()).strip()

    # ✅ AD → collapse into single group
    if "AD" in text:
        return "AD"

    return None


# =============================
# ✅ PROCESS PDF (BASE EXTRACTION)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    matched_pages = []

    for i in range(len(doc)):
        page = doc[i]
        text = extract_fast_text(page)

        if match_date(text, selected_date):
            matched_pages.append((i, text))

    if not matched_pages:
        return None, [], 0

    return doc, matched_pages, len(matched_pages)


# =============================
# ✅ BUILD FILTERED PDF
# =============================
def build_filtered_pdf(doc, matched_pages, selected_sections):

    final_pages = []

    for page_num, text in matched_pages:

        section = extract_section(text)

        # ✅ No filter → return all base pages
        if not selected_sections:
            final_pages.append(page_num)
            continue

        for sel in selected_sections:
            if section and section.startswith(sel):
                final_pages.append(page_num)
                break

    final_pages = sorted(set(final_pages))

    if not final_pages:
        return None, [], 0

    output = fitz.open()

    for p in final_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)
    buffer.seek(0)

    return buffer, final_pages, len(final_pages)


# =============================
# ✅ UI
# =============================
st.set_page_config(layout="wide")
st.title("✈️ Universal PDF Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")


if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("🛫 Processing the request..."):

            date_str = selected_date.strftime("%d %b %Y")

            doc, matched_pages, base_count = process_pdf(
                uploaded_file.read(),
                date_str
            )

            if base_count == 0:
                st.warning("⚠️ No matching pages found")

            else:
                st.success(f"✅ Base Extracted Pages: {base_count}")

                # =============================
                # ✅ DETECT AVAILABLE SECTIONS
                # =============================
                detected_sections = []

                for _, text in matched_pages:
                    sec = extract_section(text)
                    if sec:
                        detected_sections.append(sec)

                detected_sections = sorted(set(detected_sections))

                # ✅ MULTISELECT FILTER
                selected_sections = st.multiselect(
                    "📌 Filter by Section (optional)",
                    detected_sections
                )

                # =============================
                # ✅ BUILD FINAL FILTERED PDF
                # =============================
                output_pdf, final_pages, final_count = build_filtered_pdf(
                    doc,
                    matched_pages,
                    selected_sections
                )

                if final_count == 0:
                    st.warning("⚠️ No pages match selected section")

                else:
                    st.success(f"✅ Final Pages: {final_count}")

                    col_preview, col_download = st.columns([3, 1])

                    # =============================
                    # ✅ PREVIEW
                    # =============================
                    with col_preview:

                        st.subheader("📄 Preview (first 5 pages)")

                        preview_doc = fitz.open(
                            stream=output_pdf.getvalue(),
                            filetype="pdf"
                        )

                        for i in range(min(5, final_count)):
                            pix = preview_doc[i].get_pixmap()
                            st.image(pix.tobytes("png"))

                        preview_doc.close()

                    # =============================
                    # ✅ DOWNLOAD
                    # =============================
                    with col_download:

                        st.subheader("📥 Download")

                        st.download_button(
                            "Download PDF",
                            data=output_pdf,
                            file_name=f"AIP_{date_str}.pdf",
                            mime="application/pdf"
                        )
