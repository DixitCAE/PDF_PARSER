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
    "CHECKLIST",
    "DESTROY",
    "INSERT"
]

# ✅ flexible page-id + date
PAGE_DATE_PATTERN = re.compile(
    r'([A-Z0-9\-\.\/]+)\s+(\d{1,2}\s[A-Z]{3}\s\d{2,4})'
)

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


def clean_text(text):
    return re.sub(r"\s+", " ", text.upper())


def is_date_present(text, target_date):

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

    return any(p in text for p in patterns)


# ✅ supports ALL page id formats globally
def extract_page_id(text):

    patterns = [
        r'\b\d+\.\d+\-\d+\b',
        r'\b\d+\-\d+\b',
        r'AD[\s\-]*\d+\.[A-Z0-9\-]+',
        r'\b\d\-[A-Z0-9\-]+\-\d+\-\d+\b'  # Vietnam format
    ]

    for p in patterns:
        m = re.search(p, text.upper())
        if m:
            return re.sub(r"\s+", "", m.group())

    return None


# =============================
# CORE ENGINE (FINAL)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    selected_date = normalize_date(selected_date)

    matched_pages = set()

    # =============================
    # LAYER 1: CHECKLIST PARSE
    # =============================
    mapping = {}

    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text().upper() for k in CHECKLIST_KEYWORDS)
    ]

    for i in checklist_pages:

        text = clean_text(doc[i].get_text())

        matches = PAGE_DATE_PATTERN.findall(text)

        for pid, date in matches:

            pid = re.sub(r"\s+", "", pid)

            # ✅ KEEP LATEST DATE (CRITICAL FIX)
            mapping[pid] = normalize_date(date)

    # =============================
    # LAYER 2: MAP PDF PAGES
    # =============================
    page_map = {}

    for i, p in enumerate(doc):
        text = clean_text(p.get_text())
        pid = extract_page_id(text)

        if pid:
            page_map[pid] = i

    # =============================
    # LAYER 3: MATCH USING CHECKLIST
    # =============================
    for pid, date in mapping.items():

        if date == selected_date:

            if pid in page_map:

                idx = page_map[pid]
                page_text = doc[idx].get_text()

                # ✅ VALIDATION
                if is_date_present(page_text, selected_date):
                    matched_pages.add(idx)

    # =============================
    # LAYER 4: FULL SCAN FALLBACK
    # =============================
    if len(matched_pages) == 0:

        for i, p in enumerate(doc):
            full_text = p.get_text()

            if is_date_present(full_text, selected_date):
                matched_pages.add(i)

    matched_pages = sorted(matched_pages)

    # =============================
    # SAFETY
    # =============================
    if len(matched_pages) == 0:
        return None, None, 0

    # =============================
    # OUTPUT + PREVIEW
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

st.title("✈️ Universal AIP Parser (All Countries)")

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

                st.subheader("📄 Preview")

                for i, img in enumerate(preview_images):
                    st.image(img, caption=f"Page {i+1}", use_container_width=True)

                st.download_button(
                    "📥 Download PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )
