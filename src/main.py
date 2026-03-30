from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
import urllib.request
from urllib.parse import urlparse
import tempfile
from collections import Counter

# Import YOUR logic from the other file
from .pdf_compliance_analyzer import analyze_pdf, generate_llm_fix

app = FastAPI(title="PDF Accessibility Compliance Engine")

# =============================================================================
# HELPER: FILE LOCATOR RESOLVER
# =============================================================================
def resolve_file_locator(locator: str) -> tuple[str, bool]:
    """
    Translates web URLs and file:// locators into real local file paths.
    Returns the file path and a boolean indicating if it's a temporary file.
    """
    try:
        if locator.startswith("file://"):
            return urllib.request.url2pathname(urlparse(locator).path), False
        elif locator.startswith("http://") or locator.startswith("https://"):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            urllib.request.urlretrieve(locator, tmp.name)
            return tmp.name, True
        else:
            return locator, False
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not resolve file locator {locator}: {str(e)}")


# =============================================================================
# 1. Pydantic Models (The strict JSON output shapes)
# =============================================================================
class FileRequest(BaseModel): fileUrls: List[str]

class ScanIssue(BaseModel): description: str; standard: str; category: str
class ScanFileResult(BaseModel): fileName: str; nonCompliancePercent: int; complianceStatus: str; issues: List[ScanIssue]
class WorstFile(BaseModel): fileName: str; nonCompliancePercent: int
class ScanResponse(BaseModel): files: List[ScanFileResult]; worstFile: WorstFile

class RemediateIssue(BaseModel): description: str; standard: str; fix: str
class RemediateFileResult(BaseModel): fileName: str; issues: List[RemediateIssue]
class RemediateResponse(BaseModel): files: List[RemediateFileResult]

class StatusCount(BaseModel): status: str; count: int
class TypeCount(BaseModel): type: str; count: int
class StandardCount(BaseModel): standard: str; count: int
class DashboardResponse(BaseModel):
    totalScanned: int; totalIssues: int; totalFixable: int
    complianceBreakdown: List[StatusCount]
    topIssueTypes: List[TypeCount]
    standardViolationFrequency: List[StandardCount]


# =============================================================================
# 2. THE ENDPOINTS (Now powered by analyze_pdf)
# =============================================================================

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/scan", response_model=ScanResponse)
def scan_pdfs(request: FileRequest, analysis_level: str = "basic"):
    if not request.fileUrls:
        raise HTTPException(status_code=422, detail="The 'fileUrls' list cannot be empty.")

    use_llm_for_analysis = (analysis_level == "advanced")
    api_key = os.environ.get("GEMINI_API_KEY") if use_llm_for_analysis else None

    files_response: List[ScanFileResult] = []
    for locator in request.fileUrls:
        local_path, is_temp = None, False
        try:
            print(f"Processing file locator: {locator}")
            local_path, is_temp = resolve_file_locator(locator)
            result = analyze_pdf(local_path, analysis_level=analysis_level, use_llm=use_llm_for_analysis, api_key=api_key)
            file_name = os.path.basename(locator)
            
            issues = []
            for check in result.get("checks", []):
                if not check["passed"] and not check["is_na"]:
                    issues.append(ScanIssue(
                        description=check["description"],
                        standard=check["standard"],
                        category=check["category"]
                    ))
            
            files_response.append(ScanFileResult(
                fileName=file_name,
                nonCompliancePercent=result.get("nonCompliancePercent", 0),
                complianceStatus=result.get("complianceStatus", "compliant"),
                issues=issues
            ))
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.remove(local_path)


    if not files_response:
         return ScanResponse(files=[], worstFile=None)

    worst_file_result = max(files_response, key=lambda item: item.nonCompliancePercent)
    
    worst_file = WorstFile(
        fileName=worst_file_result.fileName,
        nonCompliancePercent=worst_file_result.nonCompliancePercent
    )

    return ScanResponse(files=files_response, worstFile=worst_file)


@app.post("/api/v1/remediate", response_model=RemediateResponse)
def remediate_pdfs(request: FileRequest):
    files_response = []
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY environment variable not set. Remediation is unavailable.")

    for locator in request.fileUrls:
        local_path, is_temp = None, False
        try:
            local_path, is_temp = resolve_file_locator(locator)
            # Remediation always uses basic checks, no LLM visual analysis
            result = analyze_pdf(local_path, analysis_level="basic", use_llm=False, api_key=None) 

            issues = []
            for check in result.get("checks", []):
                if not check["passed"] and not check["is_na"]:
                    fix_suggestion = generate_llm_fix(
                        issue_description=check["description"],
                        standard=check["standard"],
                        api_key=api_key
                    )
                    issues.append(RemediateIssue(
                        description=check["description"],
                        standard=check["standard"],
                        fix=fix_suggestion
                    ))
            
            files_response.append(RemediateFileResult(
                fileName=os.path.basename(locator),
                issues=issues
            ))
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.remove(local_path)

    return RemediateResponse(files=files_response)


@app.post("/api/v1/dashboard", response_model=DashboardResponse)
def get_dashboard(request: FileRequest, analysis_level: str = "basic"):
    total_scanned = len(request.fileUrls)
    total_issues = 0

    use_llm_for_analysis = (analysis_level == "advanced")
    api_key = os.environ.get("GEMINI_API_KEY") if use_llm_for_analysis else None

    status_counter = Counter()
    type_counter = Counter()
    standard_counter = Counter()

    for locator in request.fileUrls:
        local_path, is_temp = None, False
        try:
            local_path, is_temp = resolve_file_locator(locator)
            result = analyze_pdf(local_path, analysis_level=analysis_level, use_llm=use_llm_for_analysis, api_key=api_key)

            status_counter[result.get("complianceStatus", "compliant")] += 1

            for check in result.get("checks", []):
                if not check["passed"] and not check["is_na"]:
                    total_issues += 1
                    check_name = check["check"].replace("LLM: ", "")
                    type_counter[check_name] += 1
                    standard_counter[check["standard"]] += 1
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.remove(local_path)

    return DashboardResponse(
        totalScanned=total_scanned,
        totalIssues=total_issues,
        totalFixable=total_issues,
        complianceBreakdown=[StatusCount(status=k, count=v) for k, v in status_counter.items()],
        topIssueTypes=[TypeCount(type=k, count=v) for k, v in type_counter.most_common()],
        standardViolationFrequency=[StandardCount(standard=k, count=v) for k, v in standard_counter.items()]
    )
