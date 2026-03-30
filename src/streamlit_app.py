import streamlit as st
import tempfile
import os
import pandas as pd
from collections import Counter

# Import YOUR logic from the other file!
from pdf_compliance_analyzer import analyze_pdf, generate_llm_fix

# ─── PAGE CONFIGURATION ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="PDF Accessibility Dashboard",
    page_icon="📄",
    layout="wide"
)

st.title("📄 PDF Accessibility Compliance Dashboard")
st.markdown("Upload your PDF files below to instantly analyze them against WCAG, PDF/UA, and Section 508 standards.")

# ─── LLM ENHANCEMENT CONTROLS ─────────────────────────────────────────────────
st.sidebar.title("⚙️ Analysis Options")

# API Key input is now at the top and always visible
api_key = st.sidebar.text_input(
    "Enter your Gemini API Key", 
    type="password", 
    help="Required for all AI features (visual analysis and fix generation)."
)

analysis_level_option = st.sidebar.radio(
    "Select Analysis Level:",
    ("Advanced (Full Checks + LLM)", "Basic (Hackathon Checks Only)"),
    index=0, # Default to Advanced
    help="Advanced runs all programmatic checks plus optional LLM visual analysis. Basic runs only the original 7 programmatic checks."
)

analysis_level = "advanced" if analysis_level_option == "Advanced (Full Checks + LLM)" else "basic"

# LLM visual analysis is only available in advanced mode
use_llm_for_visual_analysis = False

if analysis_level == "advanced":
    # The checkbox is disabled if no API key is provided, clarifying the dependency
    use_llm_for_visual_analysis = st.sidebar.checkbox(
        "Enable Advanced LLM Analysis 🤖",
        value=True, 
        help="Runs slow, expensive visual analysis. Requires API key.",
        disabled=(not api_key) # Disable checkbox if no key is entered
    )
else:
    st.sidebar.markdown("*(LLM Visual Analysis disabled in Basic mode)*")


st.sidebar.markdown("---")
st.sidebar.header("Workflow Controls")

if st.sidebar.button("Re-run Analysis", help="Clears the cache and runs the analysis again on the current files with the selected options."):
    st.cache_data.clear()

if st.sidebar.button("Clear Uploaded Files", help="Removes all uploaded files and resets the interface."):
    st.session_state.uploader_key += 1
    st.session_state.fixes = {}
    st.rerun()


# This wrapper function will cache the analysis results
@st.cache_data
def run_and_cache_analysis(file_content, file_name, _analysis_level, _use_llm, _api_key):
    """
    A wrapper around analyze_pdf to enable caching.
    Note: Caching is based on the hash of the input arguments. We pass file_content
    to ensure the cache is invalidated if the file changes.
    The _api_key is passed to invalidate the cache if the key changes, which might imply a different model or permissions.
    """
    spinner_text = f"Analyzing {file_name}..."
    if _use_llm:
        spinner_text = f"Performing advanced visual analysis on {file_name} (this may take a moment)..."
    
    with st.spinner(spinner_text):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name
        
        try:
            # We pass the api key to the analysis function if visual analysis is enabled
            api_key_for_analysis = _api_key if _use_llm else None
            result = analyze_pdf(
                tmp_path,
                analysis_level=_analysis_level,
                use_llm=_use_llm,
                api_key=api_key_for_analysis
            )
            result["fileName"] = file_name
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    return result

# ─── FILE UPLOADER ────────────────────────────────────────────────────────────
# Initialize session state for the uploader key
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

uploaded_files = st.file_uploader(
    "Upload PDF Documents", 
    type=["pdf"], 
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.uploader_key}" # Use the dynamic key
)

if uploaded_files:
    st.write("---")

    all_results = []
    # Loop through uploaded files and get results from the cached function
    for uploaded_file in uploaded_files:
        result = run_and_cache_analysis(
            uploaded_file.getvalue(),
            uploaded_file.name,
            analysis_level,
            use_llm_for_visual_analysis,
            api_key # Pass the key to the cache function to ensure re-run if key changes
        )
        all_results.append(result)

    # ─── TABS FOR UI LAYOUT ───────────────────────────────────────────────────
    tab1, tab2 = st.tabs(["📊 High-Level Dashboard", "📑 Detailed File Reports"])

    # ==========================================================================
    # TAB 1: THE DASHBOARD (Aggregate Math & Charts)
    # ==========================================================================
    with tab1:
        st.header("Batch Overview")

        # Calculate totals
        total_scanned = len(all_results)
        total_issues = 0
        status_counter = Counter()
        type_counter = Counter()

        for r in all_results:
            status_counter[r.get("complianceStatus", "compliant")] += 1
            for check in r.get("checks", []):
                if not check["passed"] and not check["is_na"]:
                    total_issues += 1
                    check_name = check["check"].replace("LLM: ", "") # Aggregate LLM checks under one name
                    type_counter[check_name] += 1

        # Display Top-Level Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total PDFs Scanned", total_scanned)
        col2.metric("Total Accessibility Issues", total_issues)
        col3.metric("Compliant Files ✅", status_counter.get("compliant", 0))
        col4.metric("Non-Compliant Files ❌", status_counter.get("non-compliant", 0) + status_counter.get("partially-compliant", 0))

        st.write("---")

        # Display Charts
        colA, colB = st.columns(2)

        with colA:
            st.subheader("Compliance Breakdown")
            if status_counter:
                status_df = pd.DataFrame(list(status_counter.items()), columns=["Status", "Count"])
                st.bar_chart(status_df.set_index("Status"))
            else:
                st.info("No data to display.")

        with colB:
            st.subheader("Most Common Issues")
            if type_counter:
                # Sort by count descending for the chart
                type_df = pd.DataFrame(type_counter.most_common(), columns=["Issue Type", "Count"])
                st.bar_chart(type_df.set_index("Issue Type"))
            else:
                st.info("No issues found! Great job.")

    # ==========================================================================
    # TAB 2: DETAILED REPORTS (Per-file breakdown)
    # ==========================================================================
    with tab2:
        st.header("File Breakdown")

        # Use a unique key for session state based on the current batch of files
        # This prevents fixes from a previous analysis from showing up on a new one
        file_names_key = ",".join(sorted([f.name for f in uploaded_files]))
        if "fixes" not in st.session_state or st.session_state.get("file_key") != file_names_key:
            st.session_state.fixes = {}
            st.session_state.file_key = file_names_key

        for i, r in enumerate(all_results):
            # Determine color and icon based on status
            status = r["complianceStatus"].upper()
            if status == "COMPLIANT":
                icon, color = "✅", "green"
            elif status == "PARTIALLY-COMPLIANT":
                icon, color = "⚠️", "orange"
            else:
                icon, color = "❌", "red"

            # Create a collapsible expander for each file
            with st.expander(f"{icon} {r['fileName']} — {status} ({r['nonCompliancePercent']}% non-compliant)"):

                # Add a button to generate fixes if there are failures and an API key is present
                if r['failedCount'] > 0 and api_key:
                    if st.button(f"🤖 Generate Fixes for {r['fileName']}", key=f"fix_btn_{i}_{r['fileName']}"):
                        with st.spinner(f"Generating AI-powered fix suggestions for {r['fileName']}..."):
                            for check in r['checks']:
                                if not check['passed'] and not check['is_na']:
                                    # Generate a unique key for each check to store its fix
                                    fix_key = f"{r['fileName']}_{check['check']}"
                                    if fix_key not in st.session_state.fixes:
                                        st.session_state.fixes[fix_key] = generate_llm_fix(
                                            issue_description=check['description'],
                                            standard=check['standard'],
                                            api_key=api_key
                                        )

                # Format the checks into a Pandas DataFrame for a beautiful table
                table_data = []
                for c in r["checks"]:
                    res = "➖ N/A" if c["is_na"] else ("✅ PASS" if c["passed"] else "❌ FAIL")
                    check_name = c['check']
                    if check_name.startswith("LLM:"):
                         check_name = f"🤖 {check_name}"

                    row = {
                        "Check": check_name,
                        "Result": res,
                        "Description": c["description"],
                        "Standard": c["standard"],
                        "Category": c["category"]
                    }

                    # Check if a fix exists in the session state for this check
                    fix_key = f"{r['fileName']}_{c['check']}"
                    if fix_key in st.session_state.fixes:
                        row["Suggested Fix 🤖"] = st.session_state.fixes[fix_key]

                    table_data.append(row)

                df = pd.DataFrame(table_data)

                # Display the dataframe, replacing deprecated `use_container_width`
                st.dataframe(df, hide_index=True)
else:
    st.info("Please upload one or more PDFs to begin the analysis.")