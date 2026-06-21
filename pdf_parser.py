import streamlit as st
import pymupdf  # ✅ use this instead of fitz
fitz = pymupdf

import re
from datetime import datetime
from io import BytesIO

# =============================
# CONFIG
# =============================
CHECKLIST_KEYWORDS = [
    "CHECKLIST OF AIP PAGES",
    "CHECKLIST OF EAIP PAGES",
    "LISTE RECAPITULATIVE DES PAGES"
]

PAGE_DATE_PATTERN = re.compile(r'([A-Z0-9\.\-\/]+)\s+(\d{1,2}\s[A-Z]{3}\s\d{2,4})')

# =============================
# NORMALIZATION
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


# =============================
# HEADER / FOOTER EXTRACTION
# =============================
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
# CORE FUNCTION
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    # STEP 1 → FIND CHECKLIST
    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text() for k in CHECKLIST_KEYWORDS)
    ]

    # STEP 2 → EXTRACT MAPPING
    mapping = {}
    for i in checklist_pages:
        text = doc[i].get_text().replace("\n", " ")
        matches = PAGE_DATE_PATTERN.findall(text)

        for pid, date in matches:
            mapping[normalize_page_id(pid)] = normalize_date(date)

    # STEP 3 → MAP PAGE IDS
    page_map = {}
    for i, p in enumerate(doc):
        text = extract_header_footer(p)

        m = re.search(r'\b\d+\.\d+\-\d+\b|AD\-2\.[A-Z0-9\-]+', text)
        if m:
            page_map[normalize_page_id(m.group())] = i

    # STEP 4 → FILTER
    selected_date = normalize_date(selected_date)
    matched_pages = []

    for pid, date in mapping.items():
        if date == selected_date and pid in page_map:
            matched_pages.append(page_map[pid])

    matched_pages = sorted(set(matched_pages))

    # STEP 5 → CREATE OUTPUT
    output = fitz.open()

    for p in matched_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)

    output.close()
    doc.close()

    buffer.seek(0)

    return buffer, len(matched_pages)


# =============================
# STREAMLIT UI
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

            try:
                date_str = selected_date.strftime("%d %b %Y")

                output_pdf, count = process_pdf(
                    uploaded_file.read(),
                    date_str
                )

                if count == 0:
                    st.warning("⚠️ No matching pages found")
                else:
                    st.success(f"✅ Extracted {count} pages")

                    st.download_button(
                        label="📥 Download PDF",
                        data=output_pdf,
                        file_name=f"AIP_{date_str}.pdf",
                        mime="application/pdf"
                    )

            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
