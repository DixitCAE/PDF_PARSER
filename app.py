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


# ✅ HEADER-BASED PAGE ID (FIXED)
def extract_page_id_from_header(page):

    blocks = page.get_text("blocks")
    h = page.rect.height

    header_text = ""
    footer_text = ""

    for b in blocks:
        y0, y1, text = b[1], b[3], b[4]

        if y1 < h * 0.25:
            header_text += text + " "
        elif y0 > h * 0.75:
            footer_text += text + " "

    hf = clean_text(header_text + " " + footer_text)

    patterns = [
        r'\b\d+\.\d+\-\d+\b',              # 3.2-1
        r'ENR\s*\d+\.\d+\-\d+',            # ENR 3.2-1
        r'GEN\s*\d+\.\d+\-\d+',
        r'AD\s*\d+\.[A-Z0-9\-]+'           # AD-2.RCTP-1
    ]

    for p in patterns:
        m = re.search(p, hf)
        if m:
            return re.sub(r"\s+", "", m.group())

    return None


# =============================
# CORE ENGINE (FINAL STABLE)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    selected_date = normalize_date(selected_date)

    matched_pages = set()

    # =============================
    # STEP 1: CHECKLIST
    # =============================
    checklist_pages = [
        i for i, p in enumerate(doc)
        if any(k in p.get_text().upper() for k in CHECKLIST_KEYWORDS)
    ]

    mapping = {}

    for i in checklist_pages:
        text = clean_text(doc[i].get_text())

        matches = PAGE_DATE_PATTERN.findall(text)

        for pid, date in matches:
            pid = re.sub(r"\s+", "", pid)

            # ✅ keep latest date only
            mapping[pid] = normalize_date(date)

    # =============================
    # STEP 2: PAGE MAP (HEADER ONLY)
    # =============================
    page_map = {}

    for i, p in enumerate(doc):
        pid = extract_page_id_from_header(p)

        if pid:
            # normalize
            pid = pid.replace("ENR", "").replace("GEN", "").replace("AD", "")
            pid = pid.strip()

            page_map[pid] = i

    # =============================
    # STEP 3: CHECKLIST MATCH
    # =============================
    for pid, date in mapping.items():

        pid_clean = pid.replace("ENR", "").replace("GEN", "").replace("AD", "").strip()

        if date == selected_date and pid_clean in page_map:

            idx = page_map[pid_clean]

            full_text = doc[idx].get_text()

            if is_date_present(full_text, selected_date):
                matched_pages.add(idx)

    # =============================
    # ✅ FALLBACK: ALWAYS WORK
    # =============================
    if len(matched_pages) == 0:

        for i, p in enumerate(doc):

            # ✅ USE FULL TEXT (CRITICAL FIX)
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
# UI (WITH DOWNLOAD)
# =============================
st.set_page_config(layout="wide")

st.title("✈️ Universal AIP Extractor")

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

                # ✅ DOWNLOAD BUTTON (FIXED)
                st.download_button(
                    label="📥 Download Filtered PDF",
                    data=output_pdf,
                    file_name=f"AIP_{date_str}.pdf",
                    mime="application/pdf"
                )
