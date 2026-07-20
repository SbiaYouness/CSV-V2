# Implementation Plan - EBA Pillar 3 PDF & Excel Reconciliation

This final plan outlines the technical direction to upgrade the banking reconciliation application. The goal is to provide a highly accurate, deterministic comparison engine while integrating AI for summarization and setting the foundation for future RAG (Retrieval-Augmented Generation) capabilities.

---

## 1. Core Architecture & Technical Direction

The system will prioritize **deterministic, rule-based extraction** for maximum accuracy and consistency when generating the final Excel file. AI will be utilized primarily for the analytical summary and as a structured fallback for unreadable documents, laying the groundwork for a future conversational interface.

### A. File Management & UI
*   **Side-by-Side Interface**: Instead of drag-and-drop, the frontend will call a new `/api/files` endpoint.
    *   **Left Pane**: Lists available PDF ZIP files in `FichiersClaude/pdfs/`, allowing the user to check/uncheck the banks they want to reconcile.
    *   **Right Pane**: Lists available input Excel workbooks in `FichiersClaude/`.
*   **Execution**: The user selects the inputs and clicks "Analyze". The backend processes the selected ZIPs against the selected Excel workbook.

### B. LEI Mapping (Permanent Identifiers)
*   *Note on LEIs*: Legal Entity Identifiers (LEIs) are standard, globally unique, and **permanent** 20-character ISO 17442 codes assigned to entities. A bank's LEI **does not change**.
*   We will hardcode the 29-bank mapping dictionary (Bank Name $\leftrightarrow$ LEI) in the backend. This guarantees that columns in the input Excel are perfectly matched to the correct ZIP file and output row, every time.

### C. Extraction Pipeline & Open-Source OCR
1.  **Unzipping**: Extract PDFs from the selected ZIP files in memory or a temporary directory.
2.  **Text Detection**: Check if the PDF contains selectable text (e.g., `len(page.get_text()) > 1000`).
3.  **Readable PDFs (Deterministic)**:
    *   Locate target pages by searching for EBA template keywords (`"KM1"`, `"OV1"`).
    *   Use highly targeted regex patterns (already present in `pdf_parser.py`) to extract the 14 mandatory indicators.
4.  **Scanned PDFs (Open-Source OCR)**:
    *   For PDFs without text (like the BNP Paribas 310-page scan), we will integrate **Open-Source OCR** (e.g., `pytesseract` via Tesseract-OCR, or `easyocr`).
    *   To keep processing fast, we will convert PDF pages to images (using PyMuPDF's `get_pixmap()`) and run the open-source OCR engine.
    *   *Technical constraint*: If Tesseract is not installed on the host system, we will use `easyocr` (pure Python, though larger dependency) or prompt the user for the preferred local OCR engine.

### D. Efficient Storage & Caching
*   **JSON File Cache**: Every successful extraction (OCR or text) will be saved to `backend/cache/<LEI>_<Date>.json`.
*   **Token & Time Savings**: If the cache exists, the system loads the 14 indicators instantly. This makes repeat runs, debugging, and future AI tasks extremely fast and avoids redundant OCR processing.

---

## 2. Future-Proofing for AI & RAG

While the immediate goal is to reliably generate the Excel file consistently and correctly, the backend architecture will be structured to easily support the future features requested:

*   **Current AI Scope**: Generate a brief financial summary of the reconciliation (identifying gaps and anomalies) using the local Ollama instance (`qwen2.5:1.5b`).
*   **Foundation for Future RAG / Chatbot**:
    *   Because we cache the extracted text and page numbers for every PDF, a future chatbot will have instant access to the source text.
    *   Future commands like *"Which banks failed the LCR test?"* can be handled by passing the structured reconciliation JSON directly to the LLM.
    *   Future commands like *"Re-run the comparison, but only for December 31st"* will be easily supported by the new API design, which decouples file selection from execution.

---

## 3. Step-by-Step Implementation

### Step 1: Backend Setup & Caching
*   Create `backend/services/cache_service.py` to handle reading/writing extraction results.
*   Update `backend/requirements.txt` to include `pytesseract` and `pdf2image` (or `easyocr`).

### Step 2: Extraction & OCR Integration
*   Modify `pdf_parser.py` to handle `.zip` files natively.
*   Implement `extract_with_ocr()` using the chosen open-source OCR library.
*   Implement the page-filtering logic to ensure only relevant pages are OCR'd/parsed, keeping the process fast.

### Step 3: Comparison & Excel Generation
*   Update `comparator.py` with the permanent `BANK_LEI_MAP`.
*   Write the Excel generator function using `pandas` / `openpyxl` to output the exact 9-column format requested (`Entité`, `LEI`, `Indicateur`, `Valeur resultats`, `Valeur PDF (EBA)`, `Ecart`, `Ecart %`, `Statut`, `Source PDF`).

### Step 4: API & Frontend Overhaul
*   Add `/files` and `/reconcile` endpoints in `app.py`.
*   Rewrite `UploadWorkspace.tsx` to display the side-by-side lists of PDFs and Excel workbooks dynamically fetched from the backend.
*   Update `App.tsx` state management to handle the new selection flow.

---

## Review & Approval

Please review the technical details above. If you are satisfied with the deterministic extraction approach, the permanent LEI mapping, and the open-source OCR strategy, **approve this plan** and I will begin the execution phase immediately.
