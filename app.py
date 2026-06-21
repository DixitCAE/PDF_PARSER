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

PAGE_DATE_PATTERN = re.compile(
    r'([A-Z0-9\.\-\/]+)\s+(\d{1,2}\s[A-Z]{3}\s\d{2,4})'
)

# =============================
# HELPERS
# =============================
def normalize_date(date_str):
    date_str = date_str.upper().strip()
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


# =============================
# CORE LOGIC (FINAL)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    selected_date = normalize_date(selected_date)

    matched_pages = []
    mapping = {}

    # =============================
    # STEP 1: CHECK CHECKLIST EXISTS
    # =============================
    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text() for k in CHECKLIST_KEYWORDS)
    ]

    # =============================
    # CASE 1: CHECKLIST FOUND
    # =============================
    if len(checklist_pages) > 0:

        # Extract mapping
        for i in checklist_pages:
            text = doc[i].get_text().replace("\n", " ")
            matches = PAGE_DATE_PATTERN.findall(text)

            for pid, date in matches:
                mapping[normalize_page_id(pid)] = normalize_date(date)

        # Map page IDs to actual pages
        page_map = {}

        for i, p in enumerate(doc):
            text = extract_header_footer(p)

            m = re.search(r'\b\d+\.\d+\-\d+\b|AD\-2\.[A-Z0-9\-]+', text)
            if m:
                page_map[normalize_page_id(m.group())] = i

        # Match pages
        for pid, date in mapping.items():
            if date == selected_date and pid in page_map:
                matched_pages.append(page_map[pid])

    # =============================
    # CASE 2: NO CHECKLIST → FALLBACK
    # =============================
    else:
        for i, p in enumerate(doc):
            text = extract_header_footer(p).upper()

            if selected_date in text:
                matched_pages.append(i)

    matched_pages = sorted(set(matched_pages))

    # =============================
    # SAFETY (NO CRASH)
    # =============================
    if len(matched_pages) == 0:
        return None, None, 0

    # =============================
    # CREATE OUTPUT + PREVIEW
    # =============================
    output = fitz.open()
    images = []

    for p in matched_pages:

        # add to pdf
        output.insert_pdf(doc, from_page=p, to_page=p)

        # generate preview
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(1.5, 1.5))

        img = Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

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
    uploaded_file = st.file_uploader(
        "Upload AIP PDF",
        type=["pdf"]
    )

with col2:
    selected_date = st.date_input("Select Effective Date")

if uploaded_file:
    st.success("✅ File uploaded")

    if st.button("🚀 Parse and Extract"):

        with st.spinner("Processing PDF..."):

            try:
                date_str = selected_date.strftime("%d %b %Y")

                output_pdf, preview_images, count = process_pdf(
                    uploaded_file.read(),
                    date_str
                )

                if count == 0 or output_pdf is None:
                    st.warning("⚠️ No matching pages found")
                else:
                    st.success(f"✅ Found {count} pages")

                    # =============================
                    # PREVIEW SECTION
                    # =============================
                    st.subheader("📄 Page Preview")

                    for i, img in enumerate(preview_images):
                        st.image(
                            img,
                            caption=f"Page {i+1}",
                            use_container_width=True
                        )

                    # =============================
                    # DOWNLOAD BUTTON
                    # =============================
                    st.download_button(
                        label="📥 Download Filtered PDF",
                        data=output_pdf,
                        file_name=f"AIP_{date_str}.pdf",
                        mime="application/pdf"
                    )

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
