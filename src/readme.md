# 📄 PDF Accessibility Compliance Engine (Advanced)

This project is a comprehensive, AI-enhanced toolkit for analyzing PDF documents against major accessibility standards (WCAG 2.1, PDF/UA, Section 508). It provides a robust, multi-faceted analysis by combining fast, programmatic checks with deep, contextual, and visual analysis powered by Google's Gemini Pro model.

The engine offers a full suite of interfaces for different users: a powerful RESTful API for system integrations, an interactive and user-friendly web dashboard for visual analysis, and a flexible command-line tool for scripting and direct checks.

---

## ✨ Key Features

- **Dual-Level Programmatic Scanning:**
  - **Basic Mode:** Runs a core set of 7 programmatic checks, designed for speed and compatibility with baseline test cases.
  - **Advanced Mode:** Runs an extended set of 12 programmatic checks, covering more nuanced technical requirements like bookmarks, tab order, and permissions.
- **Hybrid AI Visual Analysis:** In "Advanced" mode, the engine can use a multimodal LLM to visually inspect PDF pages, identifying issues that programmatic scanners miss, such as:
  - Poor color contrast.
  - Illogical reading order.
  - Inadequate alt-text quality (not just its presence).
  - Unclear link text or table structures.
- **AI-Powered Remediation:** For any identified issue, the interactive web dashboard allows users to generate specific, actionable fix suggestions with the click of a button.
- **Multiple Interfaces:**
  - **RESTful API (FastAPI):** High-performance, fully-featured API for programmatic access.
  - **Interactive Web UI (Streamlit):** A rich, graphical dashboard for drag-and-drop file analysis, easy configuration of analysis levels, and on-demand remediation.
  - **Command-Line Interface (CLI):** A flexible tool for developers and power users to run analyses directly from the terminal.

---

## 📂 Project Structure

- `main.py`: The FastAPI web server that exposes the RESTful API endpoints.
- `pdf_compliance_analyzer.py`: The core logic of the application. Contains all programmatic checks, orchestrates the different analysis levels, and handles all interactions with the Gemini LLM.
- `streamlit_app.py`: The interactive web dashboard.
- `Dockerfile`: Defines the container for running the application, including all dependencies like Python and Poppler.
- `docker-compose.yml`: Easily starts the entire application stack using Docker.
- `requirements.txt`: A list of all Python dependencies.

---

## 🛠️ Prerequisites & Installation

### 1. System Dependencies
- **Python 3.11+**
- **Docker & Docker Compose**
- **Poppler:** This is a critical dependency required for the AI Visual Analysis feature.
  - **Windows (with Chocolatey):** `choco install poppler`
  - **macOS (with Homebrew):** `brew install poppler`
  - **Linux (Debian/Ubuntu):** `sudo apt-get update && sudo apt-get install -y poppler-utils`

### 2. Python Packages
After cloning the repository, install the required Python packages:
```bash
pip install -r requirements.txt
```

### 3. Gemini API Key
All AI-powered features (visual analysis, remediation) require a Gemini API Key.

Set it as an environment variable.
- **Windows (Command Prompt):**
  ```cmd
  setx GEMINI_API_KEY "sk-your-api-key-here"
  ```
- **Windows (PowerShell):**
  ```powershell
  $Env:GEMINI_API_KEY="sk-your-api-key-here"
  ```
- **macOS/Linux:**
  ```bash
  export GEMINI_API_KEY="sk-your-api-key-here"
  ```
To make it permanent, add the `export` command to your `.bashrc`, `.zshrc`, or shell profile.

---

## 🚀 How to Run the Project

### 1. Running with Docker (Recommended)
This is the easiest way to run the API. The `docker-compose.yml` is pre-configured to build the image and start the service.
```bash
docker compose up --build
```
The API will be available at `http://127.0.0.1:8000`. You can access the interactive API documentation (Swagger UI) at `http://127.0.0.1:8000/docs`.

### 2. Using the REST API (with cURL)

The API endpoints for scanning (`/scan`, `/dashboard`) accept an optional `analysis_level` query parameter.

- **Basic Scan (Default, for Hackathon Compliance):**
  If you don't provide the `analysis_level` parameter, it defaults to `basic`.
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/scan" 
       -H "Content-Type: application/json" 
       -d '{"fileUrls": ["file:///path/to/your/accessible_guide.pdf"]}'
  ```

- **Advanced Scan (with LLM Visual Analysis):**
  To enable all 12 programmatic checks plus the AI visual analysis, set `analysis_level=advanced`. **(Requires `GEMINI_API_KEY` to be set).**
  ```bash
  curl -X POST "http://127.0.0.1:8000/api/v1/scan?analysis_level=advanced" 
       -H "Content-Type: application/json" 
       -d '{"fileUrls": ["file:///path/to/your/untagged_report.pdf"]}'
  ```

### 3. Using the Interactive Web UI (Streamlit)

This is the best way to visually explore the analyzer's features.
```bash
streamlit run src/streamlit_app.py
```
Your browser will open to `http://localhost:8501`.

---

## 🖥️ Web UI Walkthrough

The interactive web dashboard provides a user-friendly interface for analyzing your PDFs.

### Live Demo

**[Click here to watch a video walkthrough of the web interface.](./streamlit-streamlit_app-2026-03-30-01-14-42.webm)**

*(Note: For embedding in GitHub PRs or other Markdown formats, converting this `.webm` video to a GIF is recommended.)*

### 1. Initial View & Configuration
When you first launch the app, you will see:
- A main title and a large file uploader area in the center.
- A **"⚙️ Analysis Options"** sidebar on the left.

#### Sidebar Configuration
- **Select Analysis Level:**
  - **`Advanced (Full Checks + LLM)`:** (Default) Enables all 12 programmatic checks and the option for AI visual analysis.
  - **`Basic (Hackathon Checks Only)`:** Select this to run only the 7 original checks for hackathon compliance. The LLM analysis option will be disabled.
- **Enable Advanced LLM Analysis 🤖:**
  - When in "Advanced" mode, this checkbox appears. It is enabled by default.
  - If checked, an input box will appear prompting you to **enter your Gemini API Key**. This is required for all AI features.
  
### 2. Uploading & Analysis
- Drag and drop one or more PDF files onto the uploader.
- The analysis begins automatically. A spinner will appear, indicating the analysis type being performed ("Performing basic analysis...", "Performing advanced analysis with LLM...").

### 3. Viewing Results
Once the analysis is complete, two tabs will appear:

#### 📊 High-Level Dashboard
This tab gives you a birds-eye view of the entire batch of documents.
- **Metric Cards:** Four cards at the top show `Total PDFs Scanned`, `Total Accessibility Issues`, `Compliant Files ✅`, and `Non-Compliant Files ❌`.
- **Compliance Breakdown Chart:** A bar chart visualizing the number of files in each compliance status (compliant, partially-compliant, non-compliant).
- **Most Common Issues Chart:** A bar chart showing which accessibility issues appeared most frequently across all scanned documents.

#### 📑 Detailed File Reports
This tab lets you dive into the results for each individual file.
- **Expandable Sections:** Each file has its own collapsible section, color-coded with an icon (✅, ⚠️, ❌) to indicate its compliance status.
- **Detailed Checks Table:** Inside each expander, a table lists every check that was performed.
  - **`Check`**: The name of the check. AI-found issues are marked with a 🤖 emoji.
  - **`Result`**: `✅ PASS`, `❌ FAIL`, or `➖ N/A`.
  - **`Description`**: A clear explanation of the check's result.
  - **`Standard` & `Category`**: The relevant accessibility standard and category for the check.

### 4. On-Demand AI Remediation
This is one of the most powerful features of the UI.
- If a file has one or more `❌ FAIL` results, a **`🤖 Generate Fixes for [filename]`** button will appear within its expander.
- **Clicking this button** will trigger the AI to generate a specific, actionable fix for *each* failed check in that file.
- After a moment, the detailed checks table will **automatically update** to include a new column: **`Suggested Fix 🤖`**, containing the AI's advice for each failed item.

### 4. Using the Command-Line Interface (CLI)
Navigate to the project directory and use the following commands.

- **Basic Programmatic Scan:**
  ```bash
  python src/pdf_compliance_analyzer.py --level basic "path/to/your.pdf"
  ```
- **Advanced Programmatic Scan (No LLM):**
  ```bash
  python src/pdf_compliance_analyzer.py --level advanced "path/to/your.pdf"
  ```
- **Advanced Scan with LLM Visual Analysis:**
  ```bash
  python src/pdf_compliance_analyzer.py --level advanced --llm-enhance "path/to/your.pdf"
  ```
- **Get an AI-generated Summary of Fixes:**
  ```bash
  python src/pdf_compliance_analyzer.py --llm-summary "path/to/your.pdf"
  ```
---

## 🌐 API Endpoints

- `GET /health`: Health check endpoint.
- `POST /api/v1/scan`: Analyzes a list of PDFs.
  - **Query Parameter:** `analysis_level` (string, optional, default: `"basic"`). Set to `"advanced"` to enable full checks and LLM visual analysis.
- `POST /api/v1/remediate`: Provides AI-powered fix suggestions for issues found in a PDF.
- `POST /api/v1/dashboard`: Returns aggregated statistics for a batch of PDFs.
  - **Query Parameter:** `analysis_level` (string, optional, default: `"basic"`).

## License

This project is licensed under the Apache License 2.0. See the [LICENSE.md](LICENSE) file for details.
