"""
PDF Accessibility Compliance Analyzer
======================================
Analyzes PDF files for accessibility compliance and prints results in a table.
"""

import sys
import os
import argparse
from pathlib import Path
import base64
import io
import json


# ── Optional: rich for beautiful tables ─────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# ── PDF reading ───────────────────────────────────────────────────────────────
try:
    from pypdf import PdfReader
except ImportError:
    raise ImportError("pypdf not installed. Please run: pip install -r requirements.txt")

# ── Image conversion for LLM ──────────────────────────────────────────────────
try:
    from pdf2image import convert_from_path
except ImportError:
    pass


# ── Optional: OpenAI LLM ─────────────────────────────────────────────────────
import requests
# ── Optional: OpenAI LLM ─────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  CHECKS — each returns (passed: bool, description: str, standard: str, category: str)
# ─────────────────────────────────────────────────────────────────────────────

def check_tagged(reader: PdfReader):
    root = reader.trailer.get("/Root", {})
    mark = root.get("/MarkInfo", {})
    if hasattr(mark, "get"):
        marked = mark.get("/Marked", False)
    else:
        marked = False
    passed = bool(marked)
    return (
        passed,
        "Tag tree present (/MarkInfo Marked=True)" if passed
        else "No tag tree — screen readers cannot interpret document structure",
        "PDF/UA-1 §7.1",
        "PDF/UA",
    )


def check_language(reader: PdfReader):
    root = reader.trailer.get("/Root", {})
    lang = root.get("/Lang", None)
    passed = bool(lang)
    return (
        passed,
        f"Document language declared: {lang}" if passed
        else "Document language not declared at document level",
        "WCAG 2.1 SC 3.1.1",
        "WCAG",
    )


def check_struct_tree(reader: PdfReader):
    root = reader.trailer.get("/Root", {})
    struct_tree = root.get("/StructTreeRoot")
    passed = struct_tree is not None
    return (
        passed,
        "Structure tree root present" if passed
        else "No StructTreeRoot — semantic structure unavailable to assistive tech",
        "PDF/UA-1 §7.1",
        "PDF/UA",
    )


def check_title(reader: PdfReader):
    info = reader.metadata
    title = info.get("/Title", "") if info else ""
    passed = bool(title and str(title).strip())
    return (
        passed,
        f"Document title present: '{title}'" if passed
        else "Document title missing from metadata",
        "WCAG 2.1 SC 2.4.2",
        "WCAG",
    )


def check_text_layer(reader: PdfReader):
    """Check if the first page has extractable text (not a pure scanned image)."""
    try:
        text = reader.pages[0].extract_text() or ""
        passed = len(text.strip()) > 20
    except Exception:
        passed = False
    return (
        passed,
        "Text layer extractable — document is not a scanned image" if passed
        else "No extractable text layer — document appears to be a scanned image (image-only PDF)",
        "WCAG 2.1 SC 1.4.5 / Section 508 §1194.22(d)",
        "WCAG",
    )


def check_alt_text(reader: PdfReader):
    """Walk StructTreeRoot for Figure elements missing /Alt."""
    root = reader.trailer.get("/Root", {})
    struct_root_ref = root.get("/StructTreeRoot")
    if not struct_root_ref:
        return (
            True,
            "Check not applicable: Document has no structure tree to check for figures.",
            "WCAG 2.1 SC 1.1.1",
            "WCAG",
        )

    missing_alt = []
    visited = set()

    def walk(node):
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
            obj_id = id(obj)
            if obj_id in visited:
                return
            visited.add(obj_id)
            if not isinstance(obj, dict):
                return
            s_type = obj.get("/S", "")
            if hasattr(s_type, "get_object"):
                s_type = s_type.get_object()
            if str(s_type) in ("/Figure", "Figure"):
                alt = obj.get("/Alt", None)
                if alt is None:
                    missing_alt.append(str(s_type))
            kids = obj.get("/K", [])
            if not isinstance(kids, list):
                kids = [kids]
            for kid in kids:
                walk(kid)
        except Exception:
            pass

    try:
        walk(struct_root_ref)
    except Exception as e:
        pass

    passed = len(missing_alt) == 0
    return (
        passed,
        "All Figure elements have alt text" if passed
        else f"{len(missing_alt)} Figure element(s) are missing alternative text (Alt attribute)",
        "WCAG 2.1 SC 1.1.1",
        "WCAG",
    )


def check_form_labels(reader: PdfReader):
    """Check if AcroForm fields have labels (/T entry)."""
    root = reader.trailer.get("/Root", {})
    acro = root.get("/AcroForm")
    if not acro:
        return (True, "No form fields — check not applicable", "Section 508 §1194.22(n)", "Section 508")

    try:
        acro_obj = acro.get_object() if hasattr(acro, "get_object") else acro
        fields = acro_obj.get("/Fields", [])
        unlabeled = 0
        for field_ref in fields:
            try:
                field = field_ref.get_object() if hasattr(field_ref, "get_object") else field_ref
                if not field.get("/T"):
                    unlabeled += 1
            except Exception:
                pass
        passed = unlabeled == 0
        return (
            passed,
            f"All form fields have labels (/T)" if passed
            else f"{unlabeled} form field(s) missing programmatic label (/T entry)",
            "Section 508 §1194.22(n)",
            "Section 508",
        )
    except Exception as e:
        return (False, f"Could not inspect AcroForm fields: {e}", "Section 508 §1194.22(n)", "Section 508")


def check_bookmarks(reader: PdfReader):
    """Check if the PDF has bookmarks (a navigable table of contents)."""
    bookmarks = reader.outline
    passed = bool(bookmarks)
    return (
        passed,
        "Bookmarks are present, providing a navigable table of contents" if passed
        else "No bookmarks found. Long documents should have bookmarks to help users navigate.",
        "WCAG 2.1 SC 2.4.5",
        "WCAG",
    )


def check_display_title_setting(reader: PdfReader):
    """Check if the PDF is set to display its document title in the viewer's title bar."""
    root = reader.trailer.get("/Root", {})
    viewer_prefs = root.get("/ViewerPreferences", {})
    displays_title = viewer_prefs.get("/DisplayDocTitle") is True
    passed = displays_title
    return (
        passed,
        "PDF is set to display its document title in the window title bar" if passed
        else "PDF is not set to display its document title in the window title bar (should be enabled).",
        "WCAG 2.1 SC 2.4.2",
        "WCAG",
    )


def check_tab_order(reader: PdfReader):
    """Check if the tab order is explicitly set to follow the document structure."""
    bad_pages = []
    for i, page in enumerate(reader.pages[:10]):
        if page.get("/Tabs", "") != "/S":
            bad_pages.append(str(i + 1))

    passed = len(bad_pages) == 0
    return (
        passed,
        "Tab order is explicitly set to follow the document's logical structure" if passed
        else f"Tab order is not explicitly set to follow document structure on page(s): {', '.join(bad_pages)}.",
        "PDF/UA-1 §7.8",
        "PDF/UA",
    )


def check_table_headers(reader: PdfReader):
    """Walk StructTreeRoot for Table elements and check for TH headers."""
    root = reader.trailer.get("/Root", {})
    struct_root_ref = root.get("/StructTreeRoot")
    if not struct_root_ref:
        return (
            True,
            "Check not applicable: Document has no structure tree to check for tables.",
            "WCAG 2.1 SC 1.3.1",
            "WCAG",
        )

    found_tables = []
    tables_with_headers = []
    visited = set()

    def walk(node):
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
            obj_id = id(obj)
            if obj_id in visited: return
            visited.add(obj_id)

            if not isinstance(obj, dict): return

            s_type = obj.get("/S", "")
            if hasattr(s_type, "get_object"): s_type = s_type.get_object()

            s_type_str = str(s_type)

            if s_type_str in ("/Table", "Table"):
                found_tables.append(obj)
                has_th = False
                q = [obj]
                visited_table_kids = set()
                while q:
                    curr = q.pop(0)
                    curr_id = id(curr)
                    if curr_id in visited_table_kids: continue
                    visited_table_kids.add(curr_id)

                    kids_obj = curr.get("/K", [])
                    if not isinstance(kids_obj, list): kids_obj = [kids_obj]

                    for kid_ref in kids_obj:
                        kid = kid_ref.get_object() if hasattr(kid_ref, "get_object") else kid_ref
                        if not isinstance(kid, dict): continue

                        kid_type = kid.get("/S", "")
                        if hasattr(kid_type, "get_object"): kid_type = kid_type.get_object()

                        if str(kid_type) in ("/TH", "TH"):
                            has_th = True
                            break
                        q.append(kid)
                    if has_th: break
                if has_th:
                    tables_with_headers.append(obj)

            kids = obj.get("/K", [])
            if not isinstance(kids, list): kids = [kids]
            for kid in kids:
                walk(kid)
        except Exception:
            pass

    try:
        walk(struct_root_ref)
    except Exception:
        pass

    if not found_tables:
        return (True, "No data tables found in the document's structure tree.", "WCAG 2.1 SC 1.3.1", "WCAG")

    passed = len(found_tables) == len(tables_with_headers)
    return (
        passed,
        f"All {len(found_tables)} data table(s) have defined headers (TH tags)." if passed
        else f"{len(found_tables) - len(tables_with_headers)} of {len(found_tables)} data table(s) are missing header tags (TH).",
        "WCAG 2.1 SC 1.3.1",
        "WCAG",
    )


def check_permissions(reader: PdfReader):
    """Check if accessibility permissions are enabled."""
    try:
        passed = reader.permissions.extract_text_and_graphics
    except AttributeError:
        passed = False

    return (
        passed,
        "Permissions allow screen readers and other assistive tech to extract text." if passed
        else "Document permissions may restrict assistive technologies from extracting content.",
        "Section 508 §504.2",
        "Section 508",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

BASIC_PROGRAMMATIC_CHECKS = [
    ("Tagged (MarkInfo)",   check_tagged),
    ("Language Declared",   check_language),
    ("Structure Tree",      check_struct_tree),
    ("Document Title",      check_title),
    ("Text Layer",          check_text_layer),
    ("Alt Text on Images",  check_alt_text),
    ("Form Field Labels",   check_form_labels),
]

FULL_PROGRAMMATIC_CHECKS = [
    ("Tagged (MarkInfo)",   check_tagged),
    ("Language Declared",   check_language),
    ("Structure Tree",      check_struct_tree),
    ("Document Title",      check_title),
    ("Display Title Pref",  check_display_title_setting),
    ("Text Layer",          check_text_layer),
    ("Bookmarks",           check_bookmarks),
    ("Alt Text on Images",  check_alt_text),
    ("Table Headers",       check_table_headers),
    ("Form Field Labels",   check_form_labels),
    ("Tab Order",           check_tab_order),
    ("Permissions",         check_permissions),
]


def analyze_pdf(path: str, analysis_level: str = 'advanced', use_llm: bool = False, api_key: str = None) -> dict:
    """Run all accessibility checks on a PDF and return a result dict."""
    try:
        reader = PdfReader(path)
    except Exception as e:
        return {"error": str(e), "fileName": Path(path).name, "path": path}

    results = []
    failed = 0
    programmatic_issues = []

    checks_to_run = FULL_PROGRAMMATIC_CHECKS
    if analysis_level == 'basic':
        checks_to_run = BASIC_PROGRAMMATIC_CHECKS
        use_llm = False 

    for check_name, check_fn in checks_to_run:
        passed, description, standard, category = check_fn(reader)
        is_na = "not applicable" in description.lower() or "no data tables found" in description.lower()
        if not passed and not is_na:
            failed += 1
            programmatic_issues.append(description)
        results.append({
            "check": check_name,
            "passed": passed,
            "is_na": is_na,
            "description": description,
            "standard": standard,
            "category": category,
        })

    if use_llm:
        if not api_key:
            results.append({"check": "LLM Visual Analysis", "passed": False, "is_na": False, "description": "Cannot run LLM analysis: API key is missing.", "standard": "N/A", "category": "AI"})
        else:
            try:
                llm_issues = get_llm_visual_analysis(path, programmatic_issues, api_key)
                
                for issue in llm_issues:
                    issue["check"] = f"LLM: {issue['check']}"
                    issue["is_na"] = False
                    issue["passed"] = False
                    results.append(issue)
                    failed += 1
            except Exception as e:
                results.append({"check": "LLM Visual Analysis", "passed": False, "is_na": False, "description": f"LLM analysis failed: {e}", "standard": "N/A", "category": "AI"})

    applicable = [r for r in results if not r["is_na"]]
    total_applicable = len(applicable)
    non_compliance_pct = round((failed / total_applicable) * 100) if total_applicable else 0

    if non_compliance_pct == 0:
        status = "compliant"
    elif non_compliance_pct < 60:
        status = "partially-compliant"
    else:
        status = "non-compliant"

    return {
        "fileName": Path(path).name,
        "path": path,
        "checks": results,
        "failedCount": failed,
        "totalApplicable": total_applicable,
        "nonCompliancePercent": non_compliance_pct,
        "complianceStatus": status,
        "error": None,
    }

# ─────────────────────────────────────────────────────────────────────────────
#  OPENAI LLM ENHANCEMENT
# ─────────────────────────────────────────────────────────────────────────────

def get_llm_visual_analysis(pdf_path: str, programmatic_issues: list, api_key: str) -> list[dict]:
    """Uses a multimodal LLM to visually inspect PDF pages for accessibility issues."""
    
    print(f"File - {pdf_path} Generating visual analysis with LLM...")  # Debug statement
    try:
        # This function relies on pdf2image, which might not be installed.
        convert_from_path

    except NameError:
        raise ImportError("The 'pdf2image' library is required for LLM analysis. Please install it (`pip install pdf2image`) and ensure Poppler is in your system's PATH.")

    # 1. Convert PDF to a list of images
    images = convert_from_path(pdf_path)

    # 2. Encode images to base64
    base64_images = []
    for image in images:
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        base64_images.append(base64.b64encode(buffered.getvalue()).decode('utf-8'))

    # 3. Create the prompt for the LLM
    issues_str = "\n".join([f"- {issue}" for issue in programmatic_issues])
    prompt_text = f"""
    You are an expert in digital accessibility, specializing in PDF documents. Your task is to find visual and contextual issues that programmatic scanners miss. Be concise.

    Programmatic analysis has already found these technical issues:
    {issues_str}
    Do NOT report these same issues again.

    Analyze the following document pages (provided as images) and identify ONLY new, additional issues based on the following criteria:
    1.  Color Contrast: Is there sufficient contrast between text and its background (WCAG 1.4.3)?
    2.  Reading Order: Does the visual layout present a logical reading order?
    3.  Alt Text Quality: For any images, is the existing alt text (if any) descriptive and meaningful?
    4.  Data Tables: Are data tables structured in a way that is easy to understand? Do they have clear visual headers?
    5.  Headings & Labels: Are headings and labels clear and descriptive of their content (WCAG 2.4.6)?
    6.  Link Text: Is the purpose of links clear from their text alone (e.g., avoid "click here")?

    For each distinct issue you find, provide a brief, clear description.
    Return your findings as a single, compact JSON array of objects. Each object must have these exact keys: "check", "description", "standard", "category".
    - "check": A short title for the issue (e.g., "Low Contrast Text").
    - "description": A concise, user-friendly explanation of the issue and where it was found.
    - "standard": The relevant accessibility standard (e.g., "WCAG 2.1 SC 1.4.3").
    - "category": The general category (e.g., "Color", "Reading Order").

    If you find no new issues, return an empty JSON array: [].
    """

    # 4. Call the LLM
    llm_response = llm_multimodal_request(prompt_text, base64_images, api_key)
    
    # 5. Parse and return the results
    try:
        # The response might be inside a markdown code block
        if "```json" in llm_response:
            llm_response = llm_response.split("```json")[1].split("```")[0]
        
        issues = json.loads(llm_response)

        if not isinstance(issues, list):
            return []
        return issues
    except (json.JSONDecodeError, IndexError):
        # The LLM failed to return valid JSON, so we can't parse any issues.
        return []


def llm_multimodal_request(prompt: str, images: list[str], api_key: str) -> str:
    """Sends a multimodal request to the LLM."""
    BASE_URL = "http://13.234.214.173:4000"
    MODEL = "gemini-2.5-flash"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Construct the messages payload with images
    content = [{"type": "text", "text": prompt}]
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img}"
            }
        })

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
        "temperature": 0.2 # Lower temperature for more deterministic, structured output
    }

    try:
        response = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=data, timeout=90)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        else:
            return f"[] # AI Error: {response.status_code} {response.text}"
    except Exception as e:
        return f"[] # AI request error: {e}"


def llm_enhance(results: list[dict], api_key: str) -> str:
    """Use a Gemini model via a custom endpoint to produce a human-readable summary and fix suggestions."""

    BASE_URL = "http://13.234.214.173:4000"
    MODEL = "gemini-2.5-flash"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Build a summary of issues for the LLM
    issues_text = []
    for r in results:
        issues = [c for c in r["checks"] if not c["passed"] and not c["is_na"]]
        if issues:
            lines = [f"File: {r['fileName']} (Status: {r['complianceStatus']}, {r['nonCompliancePercent']}% non-compliant)"]
            for i in issues:
                lines.append(f"  - [{i['standard']}] {i['description']}")
            issues_text.append("\n".join(lines))

    if not issues_text:
        return "All files are fully compliant — no issues to report."

    prompt = f"""
You are a PDF accessibility expert. Below are accessibility issues found in PDF documents.
For each issue, provide:
1. A brief, user-friendly explanation of WHY the issue matters
2. A SPECIFIC, actionable remediation step

Format your response clearly per file and issue.

Issues found:
{chr(10).join(issues_text)}
"""

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.7
    }

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=45
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            return f"Error: {response.status_code} {response.text}"
    except Exception as e:
        return f"LLM request error: {e}"


def generate_llm_fix(issue_description: str, standard: str, api_key: str) -> str:
    """Asks the Gemini LLM for a single, actionable fix for a specific issue."""

    BASE_URL = "http://13.234.214.173:4000"
    MODEL = "gemini-2.5-flash"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    prompt = f"""
You are a PDF accessibility expert.
An accessibility checker found this issue: '{issue_description}'
This violates the standard: '{standard}'

Provide a single, specific, actionable sentence explaining exactly how a user can fix this issue, for example, by using a tool like Adobe Acrobat. Do not use markdown. Do not greet the user or use any preamble.
"""

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000, # Keep it concise
        "temperature": 0.7
    }

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json=data,
            timeout=45
        )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        else:
            return f"AI Error: {response.status_code} {response.text}"
    except Exception as e:
        return f"AI request error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
#  DISPLAY — Rich table or plain text fallback
# ─────────────────────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "compliant": "green",
    "partially-compliant": "yellow",
    "non-compliant": "red",
}


def display_rich(all_results: list[dict]):
    console = Console()

    # ── Summary table ────────────────────────────────────────────────────────
    console.print("\n[bold cyan]━━━ PDF ACCESSIBILITY COMPLIANCE SUMMARY ━━━[/bold cyan]\n")
    summary = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white on dark_blue",
        title="[bold]Compliance Overview[/bold]",
        expand=True,
    )
    summary.add_column("File", style="bold")
    summary.add_column("Status", justify="center")
    summary.add_column("Non-Compliance %", justify="center")
    summary.add_column("Failed Checks", justify="center")
    summary.add_column("Total Checks", justify="center")

    for r in all_results:
        if r.get("error"):
            summary.add_row(r["fileName"], "[red]ERROR[/red]", "-", "-", "-")
            continue
        color = STATUS_COLORS.get(r["complianceStatus"], "white")
        status_text = Text(r["complianceStatus"].upper(), style=f"bold {color}")
        pct = r["nonCompliancePercent"]
        pct_text = Text(f"{pct}%", style=f"bold {color}")
        summary.add_row(
            r["fileName"],
            status_text,
            pct_text,
            str(r["failedCount"]),
            str(r["totalApplicable"]),
        )

    console.print(summary)

    # ── Per-file detailed check tables ───────────────────────────────────────
    for r in all_results:
        if r.get("error"):
            console.print(f"\n[red]ERROR reading {r['fileName']}: {r['error']}[/red]")
            continue

        color = STATUS_COLORS.get(r["complianceStatus"], "white")
        console.print(f"\n[bold]📄 {r['fileName']}[/bold]  →  "
                      f"[{color} bold]{r['complianceStatus'].upper()}[/{color} bold]  "
                      f"([{color}]{r['nonCompliancePercent']}% non-compliant[/{color}])")

        detail = Table(
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold white",
            expand=True,
        )
        detail.add_column("Check", style="bold", width=22)
        detail.add_column("Result", justify="center", width=10)
        detail.add_column("Description", ratio=3)
        detail.add_column("Standard", ratio=2)
        detail.add_column("Category", justify="center", width=12)

        for c in r["checks"]:
            is_llm_check = c.get("check", "").startswith("LLM:")
            if c["is_na"]:
                result_cell = Text("N/A", style="dim")
                desc_style = "dim"
            elif c["passed"]:
                result_cell = Text("✅ PASS", style="bold green")
                desc_style = "green"
            else:
                result_cell = Text("❌ FAIL", style="bold red")
                desc_style = "red"

            check_text = Text(c["check"], style="bold")
            if is_llm_check:
                check_text.append(" 🤖", style="dim")


            detail.add_row(
                check_text,
                result_cell,
                Text(c["description"], style=desc_style),
                c["standard"],
                c["category"],
            )

        console.print(detail)


def display_plain(all_results: list[dict]):
    """Fallback plain-text table display (no rich needed)."""
    SEP = "─" * 110
    print(f"\n{'PDF ACCESSIBILITY COMPLIANCE REPORT':^110}")
    print(SEP)
    print(f"{'File':<30} {'Status':<22} {'Non-Compliance%':>16} {'Failed/Total':>14}")
    print(SEP)
    for r in all_results:
        if r.get("error"):
            print(f"{r['fileName']:<30} {'ERROR':<22} {'-':>16} {'-':>14}")
            continue
        print(f"{r['fileName']:<30} {r['complianceStatus']:<22} {r['nonCompliancePercent']:>15}% "
              f"{r['failedCount']:>6}/{r['totalApplicable']:<6}")
    print(SEP)

    for r in all_results:
        if r.get("error"):
            continue
        print(f"\n📄 {r['fileName']}  →  {r['complianceStatus'].upper()}  ({r['nonCompliancePercent']}% non-compliant)")
        print(f"{'Check':<25} {'Result':<8} {'Standard':<35} {'Category':<12} Description")
        print("─" * 110)
        for c in r["checks"]:
            is_llm_check = c.get("check", "").startswith("LLM:")
            result = "N/A " if c["is_na"] else ("PASS" if c["passed"] else "FAIL")
            check_name = f"{c['check']}{' *' if is_llm_check else ''}"
            print(f"{check_name:<25} {result:<8} {c['standard']:<35} {c['category']:<12} {c['description']}")
        print()


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PDF Accessibility Compliance Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic programmatic scan (7 checks)
  python pdf_compliance_analyzer.py --level basic docs/fixtures/*.pdf

  # Advanced programmatic scan (12 checks)
  python pdf_compliance_analyzer.py --level advanced docs/fixtures/*.pdf

  # Advanced scan with LLM visual analysis
  python pdf_compliance_analyzer.py --level advanced --llm-enhance docs/fixtures/*.pdf

  # Get a summary of fixes for a report (run this after analysis)
  python pdf_compliance_analyzer.py --llm-summary docs/fixtures/untagged_report.pdf
        """,
    )
    parser.add_argument("pdfs", nargs="+", help="PDF file paths to analyze")
    parser.add_argument("--level", choices=['basic', 'advanced'], default='advanced', help="Set the analysis level: 'basic' for 7 core checks, 'advanced' for all 12 programmatic checks.")
    parser.add_argument("--llm-enhance", action="store_true", help="Use a multimodal LLM for advanced visual and contextual analysis (requires --level advanced).")
    parser.add_argument("--llm-summary", action="store_true", help="Use a text LLM to generate a summary of fixes for the programmatic results.")
    parser.add_argument("--api-key", default=None, help="Gemini API key (or set GEMINI_API_KEY env var)")
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")

    if (args.llm_enhance or args.llm_summary) and not api_key:
        if HAS_RICH:
            from rich import print
            print("\n[bold red]ERROR: An API key is required for LLM features. Set GEMINI_API_KEY or use --api-key.[/bold red]")
        else:
            print("\nERROR: An API key is required for LLM features. Set GEMINI_API_KEY or use --api-key.", file=sys.stderr)
        sys.exit(1)
    
    if args.llm_enhance and args.level != 'advanced':
        if HAS_RICH:
            from rich import print
            print("\n[bold yellow]WARNING: --llm-enhance is only available with --level advanced. Proceeding with basic analysis only.[/bold yellow]")
        else:
            print("\nWARNING: --llm-enhance is only available with --level advanced. Proceeding with basic analysis only.", file=sys.stderr)
        use_llm_visual = False
    else:
        use_llm_visual = args.llm_enhance


    # Analyze all PDFs
    all_results = []
    for pdf_path in args.pdfs:
        print(f"Analyzing: {pdf_path} ...")
        result = analyze_pdf(
            pdf_path, 
            analysis_level=args.level, 
            use_llm=use_llm_visual, 
            api_key=api_key
        )
        all_results.append(result)

    # Display results
    if HAS_RICH:
        display_rich(all_results)
    else:
        display_plain(all_results)
        print("\n[TIP] Install 'rich' for a much prettier output: pip install rich")

    # LLM summary enhancement
    if args.llm_summary:
        print("\n" + "━" * 60)
        print("🤖  Gemini LLM — REMEDIATION GUIDANCE SUMMARY")
        print("━" * 60)
        summary = llm_enhance(all_results, api_key)
        print(summary)


if __name__ == "__main__":
    main()
