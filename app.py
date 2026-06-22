import streamlit as st
import fitz
import re
from datetime import datetime
from io import BytesIO


# =============================
# DATE MATCH
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
        f"{day1}{month}{year_full}",
        f"{day2}{month}{year_full}",
        f"{month}{day1}{year_full}",
        f"{month}{day2}{year_full}",
        f"{day1}{month}{year_short}",
        f"{day2}{month}{year_short}",
        f"{month}{day1}{year_short}",
        f"{month}{day2}{year_short}",
    ]

    return any(p in text for p in patterns)


# =============================
# EXTRACT TEXT
# =============================
def extract_fast_text(page):
    return " ".join([b[4] for b in page.get_text("blocks")])


# =============================
# SECTION DETECTION
# =============================
def extract_section(text):

    text = text.upper()

    # GEN / ENR
    m = re.search(r'(GEN\s*(\d+))|(ENR\s*(\d+(\.\d+)?))', text)
    if m:
        return re.sub(r"\s+", " ", m.group()).strip()

    # AD
    if "AD" in text:
        m_ad = re.search(r'AD\s*(\d+)', text)
        if m_ad:
            return f"AD {m_ad.group(1)}"
        return "AD"

    return None


# =============================
# ✅ REMOVAL LOGIC (NEW)
# =============================
def should_remove(section):

    if not section:
        return True

    section = section.upper()

    remove_rules = [
        "GEN 0", "GEN 2", "GEN 3", "GEN 4",
        "ENR 0", "ENR 2", "ENR 6",
        "AD 3"
    ]

    for r in remove_rules:
        if section.startswith(r):
            return True

    return False


# =============================
# PROCESS PDF (WITH CLEANING)
# =============================
def process_pdf(file_bytes, selected_date):

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    cleaned_pages = []

    for i in range(len(doc)):

        page = doc[i]
        text = extract_fast_text(page)

        # ✅ Step 1: Match Date
        if not match_date(text, selected_date):
            continue

        # ✅ Step 2: Detect section
        section = extract_section(text)

        # ✅ Step 3: Apply removal rule
        if should_remove(section):
            continue

        cleaned_pages.append((i, text))

    return doc, cleaned_pages


# =============================
# BUILD FINAL PDF
# =============================
def build_filtered_pdf(doc, pages, selected_sections):

    final_pages = []

    for page_num, text in pages:

        section = extract_section(text)

        if not selected_sections:
            final_pages.append(page_num)
            continue

        for sel in selected_sections:
            if section and section.startswith(sel):
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
# SESSION STATE
# =============================
if "processed" not in st.session_state:
    st.session_state.processed = False


# =============================
# EXTRACT BUTTON
# =============================
if uploaded_file:

    st.success("✅ File uploaded")

    if st.button("🚀 Extract Pages"):

        with st.spinner("🛫 Processing the request..."):

            doc, cleaned_pages = process_pdf(
                uploaded_file.read(),
                selected_date.strftime("%d %b %Y")
            )

            st.session_state.doc = doc
            st.session_state.pages = cleaned_pages
            st.session_state.processed = True


# =============================
# MAIN UI
# =============================
if st.session_state.processed:

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
            st.subheader("📄 Preview")

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
