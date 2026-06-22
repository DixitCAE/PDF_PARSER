import streamlit as st
import fitz
import re
from datetime import datetime
from io import BytesIO


# =============================
# SESSION STATE INIT (FINAL FIX)
# =============================
if "processed" not in st.session_state:
    st.session_state.processed = False

if "pages" not in st.session_state:
    st.session_state.pages = []

if "doc" not in st.session_state:
    st.session_state.doc = None


# =============================
# DATE MATCH
# =============================
def match_date(text, selected_date):

    text = re.sub(r'[\s\.\-\/:\,]', '', text.upper())
    dt = datetime.strptime(selected_date, "%d %b %Y")

    d1 = str(dt.day)
    d2 = f"{dt.day:02}"
    m = dt.strftime("%b").upper()
    y_full = str(dt.year)
    y_short = y_full[-2:]

    patterns = [
        f"{d1}{m}{y_full}", f"{d2}{m}{y_full}",
        f"{m}{d1}{y_full}", f"{m}{d2}{y_full}",
        f"{d1}{m}{y_short}", f"{d2}{m}{y_short}",
        f"{m}{d1}{y_short}", f"{m}{d2}{y_short}",
    ]

    return any(p in text for p in patterns)


# =============================
# TEXT EXTRACTION
# =============================
def extract_fast_text(page):
    return " ".join([b[4] for b in page.get_text("blocks")])


# =============================
# SECTION DETECTION
# =============================
def extract_section(text):

    text = text.upper()

    m = re.search(r'(GEN\s*\d+(\.\d+)?)|(ENR\s*\d+(\.\d+)?)', text)
    if m:
        return re.sub(r"\s+", " ", m.group()).strip()

    if "AD" in text:
        m_ad = re.search(r'AD\s*(\d+)', text)
        if m_ad:
            return f"AD {m_ad.group(1)}"
        return "AD"

    return None


# =============================
# REMOVE RULES
# =============================
def should_remove(section):

    if not section:
        return True

    section = section.upper()

    rules = [
        "GEN 0", "GEN 2", "GEN 3", "GEN 4",
        "ENR 0", "ENR 2", "ENR 6",
        "AD 3"
    ]

    return any(section.startswith(r) for r in rules)


# =============================
# PROCESS PDF
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    cleaned_pages = []

    for i in range(len(doc)):

        page = doc[i]
        text = extract_fast_text(page)

        if not match_date(text, selected_date):
            continue

        sec = extract_section(text)

        if should_remove(sec):
            continue

        cleaned_pages.append((i, text))

    return doc, cleaned_pages


# =============================
# BUILD FINAL PDF
# =============================
def build_filtered_pdf(doc, pages, selected_sections):

    final_pages = []

    for page_num, text in pages:

        sec = extract_section(text)

        if not selected_sections:
            final_pages.append(page_num)
            continue

        for sel in selected_sections:
            if sec and sec.startswith(sel):
                final_pages.append(page_num)
                break

    final_pages = sorted(set(final_pages))

    output = fitz.open()
    for p in final_pages:
        output.insert_pdf(doc, from_page=p, to_page=p)

    buffer = BytesIO()
    output.save(buffer)
    buffer.seek(0)

    return buffer, final_pages, len(final_pages)


# =============================
# UI
# =============================
st.set_page_config(layout="wide")
st.title("✈️ Universal PDF Extractor")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader("Upload AIP PDF", type=["pdf"])

with col2:
    selected_date = st.date_input("Select Effective Date")


# =============================
# RUN EXTRACTION
# =============================
if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("🛫 Processing the request..."):

            doc, pages = process_pdf(
                uploaded_file.read(),
                selected_date.strftime("%d %b %Y")
            )

            st.session_state.doc = doc
            st.session_state.pages = pages
            st.session_state.processed = True


# =============================
# MAIN VIEW (SAFE FIXED)
# =============================
if st.session_state.processed and st.session_state.pages:

    doc = st.session_state.doc
    pages = st.session_state.pages

    st.success(f"✅ Cleaned Pages After Rules: {len(pages)}")

    # GROUP SECTIONS
    sections = {"GEN": [], "ENR": [], "AD": []}

    for _, text in pages:
        sec = extract_section(text)

        if sec:
            if sec.startswith("GEN"):
                sections["GEN"].append(sec)
            elif sec.startswith("ENR"):
                sections["ENR"].append(sec)
            elif sec.startswith("AD"):
                sections["AD"].append("AD")

    for k in sections:
        sections[k] = sorted(set(sections[k]))

    st.subheader("📌 Filter by Section")

    selected_sections = []

    # ✅ COLLAPSED DEFAULT
    if sections["GEN"]:
        with st.expander("GEN", expanded=False):
            for sec in sections["GEN"]:
                if st.checkbox(sec, key=f"G_{sec}"):
                    selected_sections.append(sec)

    if sections["ENR"]:
        with st.expander("ENR", expanded=False):
            for sec in sections["ENR"]:
                if st.checkbox(sec, key=f"E_{sec}"):
                    selected_sections.append(sec)

    if sections["AD"]:
        with st.expander("AD", expanded=False):
            if st.checkbox("AD", key="A_main"):
                selected_sections.append("AD")

    if selected_sections:
        st.markdown(f"### ✅ Selected: `{', '.join(selected_sections)}`")

    # BUILD FINAL
    output_pdf, final_pages, count = build_filtered_pdf(
        doc, pages, selected_sections
    )

    if count > 0:

        st.success(f"✅ Final Pages: {count}")

        col_preview, col_download = st.columns([3, 1])

        with col_preview:
            st.subheader("📄 Preview (first 5 pages)")

            preview_doc = fitz.open(
                stream=output_pdf.getvalue(),
                filetype="pdf"
            )

            for i in range(min(5, count)):
                st.image(preview_doc[i].get_pixmap().tobytes("png"))

            preview_doc.close()

        with col_download:
            st.subheader("📥 Download")

            st.download_button(
                "Download PDF",
                data=output_pdf,
                file_name="Filtered_AIP.pdf",
                mime="application/pdf"
            )
