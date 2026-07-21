import os
import uuid
import time
import zipfile
import shutil
import io
import traceback
from pathlib import Path
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from services.pdf_parser import extract_transactions, extract_bank_metrics
from services.csv_parser import read_flexible_csv
from services.comparator import compare_transactions, _lei_for_col, _output_name_for_col
from services.llm import summarize_reconciliation
from services.zip_selection import date_from_zip, lei_from_zip, select_zip_for_lei
from services.bank_hierarchy import get_bank_relationship

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
FILES_DIR = BASE_DIR / "FichiersClaude"
PDF_DIR = FILES_DIR / "pdfs"
OUTPUT_DIR = FILES_DIR / "comparaison_EBA"
UPLOAD_DIR = Path("uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = FastAPI(title="Concilio — EBA Pillar 3 Reconciliation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        print("=" * 80)
        print(f"ERROR: Exception occurred while handling {request.method} {request.url.path}")
        traceback.print_exc()
        print("=" * 80)
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "message": "Internal Server Error in FastAPI backend. Please check the terminal logs."
            }
        )

# ─── In-memory summary context store (keyed by result id) ────────────────────
# Holds the data needed to generate an AI summary on demand. Capped at 50
# entries to avoid unbounded memory growth during a session.
_SUMMARY_CONTEXTS: dict[str, dict] = {}
_SUMMARY_CONTEXT_MAX = 50


def _store_summary_context(result_id: str, ctx: dict) -> None:
    if len(_SUMMARY_CONTEXTS) >= _SUMMARY_CONTEXT_MAX:
        oldest_key = next(iter(_SUMMARY_CONTEXTS))
        del _SUMMARY_CONTEXTS[oldest_key]
    _SUMMARY_CONTEXTS[result_id] = ctx


# ─── Pydantic models ─────────────────────────────────────────────────────────
class ReconcileRequest(BaseModel):
    excel_file: str          # filename from FichiersClaude/
    zip_files: list[str]     # list of zip filenames from FichiersClaude/pdfs/
    report_date: str = ""    # e.g. "2025-12-31"


class SummaryRequest(BaseModel):
    result_id: str


def _cell_to_float(value) -> float | None:
    """Convert Excel numeric cells robustly; blank cells are not comparable."""
    if pd.isna(value):
        return None
    raw = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None

# ─── Helper: detect reporting date from zip filename ─────────────────────────
def _date_from_zip(name: str) -> str:
    """Extract YYYY-MM-DD from zip filename."""
    parts = name.split("_")
    for p in parts:
        if len(p) == 10 and p[4] == "-" and p[7] == "-":
            return p
    return ""

# ─── Helper: extract LEI from zip filename prefix ────────────────────────────
def _lei_from_zip(name: str) -> str:
    return name.split(".")[0]

# ─── Root ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Concilio — EBA Pillar 3 Reconciliation API"}


# ─── /api/files ──────────────────────────────────────────────────────────────
@app.get("/api/files")
def list_files():
    """
    Returns two lists:
     - excel_files: all .xlsx files in FichiersClaude/
     - zip_files: all .zip files in FichiersClaude/pdfs/, grouped by date
    """
    excel_files = []
    if FILES_DIR.exists():
        for f in sorted(FILES_DIR.glob("*.xlsx")):
            excel_files.append({"name": f.name, "size": f.stat().st_size})

    zip_files = []
    by_date: dict[str, list] = {}
    if PDF_DIR.exists():
        for f in sorted(PDF_DIR.glob("*.zip")):
            date = date_from_zip(f.name)
            lei = lei_from_zip(f.name)
            entry = {
                "name": f.name,
                "lei": lei,
                "date": date,
                "size": f.stat().st_size,
            }
            zip_files.append(entry)
            by_date.setdefault(date, []).append(entry)

    return {
        "excel_files": excel_files,
        "zip_files": zip_files,
        "by_date": by_date,
    }


# ─── /api/reconcile ──────────────────────────────────────────────────────────
@app.post("/api/reconcile")
def reconcile(req: ReconcileRequest):
    """
    Batch reconcile: for every bank column in the Excel file, find the
    matching ZIP by LEI, extract metrics from the PDF, and compare.
    Returns a rich JSON payload and saves the output Excel to comparaison_EBA/.
    AI synthesis is NOT generated here; call /api/summary on demand.
    """
    start = time.time()

    excel_path = FILES_DIR / req.excel_file
    if not excel_path.exists():
        return JSONResponse(status_code=404, content={"error": f"Excel file not found: {req.excel_file}"})

    selected_zip_names = [name for name in req.zip_files if (PDF_DIR / name).exists()]

    # Read the input workbook
    df_in = pd.read_excel(excel_path)
    indicator_col = df_in.columns[0]
    bank_columns = df_in.columns[1:].tolist()
    indicators = df_in[indicator_col].tolist()

    # Collect rows for the output workbook
    all_rows: list[dict] = []
    bank_results: list[dict] = []  # per-bank summary for frontend
    skipped_banks: list[dict] = []
    input_metric_values: dict[str, dict[str, float | None]] = {}
    total_matched = 0
    total_rows = 0

    for column_index, col in enumerate(bank_columns):
        output_name = _output_name_for_col(col)
        lei = _lei_for_col(col)
        relationship = get_bank_relationship(output_name)
        # Keep the configured indicator set as the denominator everywhere.  A
        # blank source cell must not make a detail row disappear while it is
        # still included in the bank-card total.
        metric_rows = [
            (str(ind_raw).strip(), _cell_to_float(cell))
            for ind_raw, cell in zip(indicators, df_in[col])
            if str(ind_raw).strip() and str(ind_raw).strip().lower() != "nan"
        ]
        input_metric_count = sum(value is not None for _, value in metric_rows)
        bank_id = f"{lei or 'unmapped'}:{column_index}"
        input_metric_values[output_name] = dict(metric_rows)

        if input_metric_count == 0:
            skipped_banks.append({
                "bank": output_name,
                "lei": lei,
                "reason": "no_input_data",
            })

        # Choose the best ZIP for this LEI and requested report date.
        zip_name = select_zip_for_lei(selected_zip_names, lei, req.report_date) if lei else None
        zip_path = PDF_DIR / zip_name if zip_name else None

        pdf_metrics: dict[str, dict] = {}
        source_label = "auto-extraction (KM1/OV1 regex)"

        if zip_path:
            raw_metrics = extract_bank_metrics(str(zip_path))
            for m in raw_metrics:
                pdf_metrics[m["Indicateur"]] = m

        bank_ok = 0
        bank_rows = 0

        for ind, result_value in metric_rows:

            pdf_entry = pdf_metrics.get(ind)
            pdf_value = pdf_entry["Valeur PDF (EBA)"] if pdf_entry else None
            source_pdf = pdf_entry["Source PDF"] if pdf_entry else ""

            # Determine status
            if not zip_path:
                if relationship and relationship.get("reports_with_parent"):
                    status = f"Données consolidées au niveau parent ({relationship['parent_group']})"
                else:
                    status = "PDF non disponible"
            elif pdf_value is None:
                status = "Non trouvé dans le PDF"
            elif result_value is None:
                status = "Absent du fichier resultats"
            else:
                delta = abs(result_value - pdf_value)
                ratio = (delta / abs(pdf_value)) if pdf_value not in (None, 0) else 0
                if delta < 0.0005 or (pdf_value == 0 and result_value == 0):
                    status = "OK"
                elif abs(result_value * 100 - pdf_value) < max(abs(pdf_value) * 0.05, 1.0):
                    status = "ANOMALIE UNITE PROBABLE (facteur ~100, fichier resultats)"
                elif ratio > 0.01:
                    status = "ECART SIGNIFICATIF"
                else:
                    status = "OK"

            ecart = None
            ecart_pct = None
            if result_value is not None and pdf_value is not None:
                ecart = result_value - pdf_value
                ecart_pct = (ecart / abs(pdf_value) * 100) if pdf_value != 0 else None

            if status == "OK":
                bank_ok += 1
            bank_rows += 1
            total_rows += 1
            if status == "OK":
                total_matched += 1

            all_rows.append({
                "bank_id": bank_id,
                "Entité": output_name,
                "LEI": lei,
                "Indicateur": ind,
                "Valeur resultats": result_value,
                "Valeur PDF (EBA)": pdf_value,
                "Ecart": ecart,
                "Ecart %": ecart_pct,
                "Statut": status,
                "Source PDF": source_pdf or source_label,
            })

        bank_results.append({
            "id": bank_id,
            "bank": output_name,
            "lei": lei,
            "matched": bank_ok,
            "total": bank_rows,
            "score": round(bank_ok / bank_rows * 100, 1) if bank_rows > 0 else 0,
            "has_pdf": bool(zip_path),
            "zip_name": zip_name or "",
            "input_metrics": input_metric_count,
            # Raw extraction can include auxiliary values.  This is the count
            # relevant to the configured reconciliation denominator.
            "pdf_metrics_found": sum(ind in pdf_metrics for ind, _ in metric_rows),
            "expected_metrics": len(metric_rows),
            "detail_rows": bank_rows,
            "parent_group": relationship.get("parent_group") if relationship else "",
            "relationship": relationship.get("relationship") if relationship else "",
            "reports_with_parent": bool(relationship and relationship.get("reports_with_parent")),
            "relationship_source": relationship.get("source") if relationship else "",
            "relationship_source_url": relationship.get("source_url") if relationship else "",
        })

    # A subsidiary relation explains absent standalone data only when the
    # relationship source explicitly supports consolidated reporting.  If the
    # source workbook is also identical to its parent's values, expose that
    # stronger explanation separately from an extraction failure.
    results_by_bank = {result["bank"]: result for result in bank_results}
    for result in bank_results:
        parent_name = result.get("parent_group")
        if not result.get("reports_with_parent") or not parent_name:
            continue
        result["reporting_context"] = "parent_group_reporting"
        parent_values = input_metric_values.get(parent_name)
        child_values = input_metric_values.get(result["bank"])
        if not parent_values or not child_values:
            continue
        shared = [
            indicator
            for indicator, value in child_values.items()
            if value is not None and parent_values.get(indicator) is not None
        ]
        if shared and all(abs(child_values[indicator] - parent_values[indicator]) < 1e-9 for indicator in shared):
            result["reporting_context"] = "identical_to_parent"
            result["parent_data_available"] = parent_name in results_by_bank

    # ─── Save Excel output ─────────────────────────────────────────────────
    report_date = req.report_date or datetime.now().strftime("%Y-%m-%d")
    out_filename = f"Comparaison_EBA_vs_resultats_{report_date}.xlsx"
    out_path = OUTPUT_DIR / out_filename

    df_out = pd.DataFrame(all_rows, columns=[
        "Entité", "LEI", "Indicateur", "Valeur resultats",
        "Valeur PDF (EBA)", "Ecart", "Ecart %", "Statut", "Source PDF"
    ])
    df_out.to_excel(out_path, index=False)

    # ─── Compute stats (no AI call — summary is on-demand via /api/summary) ─
    ok_count = sum(1 for r in all_rows if r["Statut"] == "OK")
    ecart_count = sum(1 for r in all_rows if r["Statut"] == "ECART SIGNIFICATIF")
    missing_pdf = sum(1 for r in all_rows if "non disponible" in r["Statut"])

    elapsed = round(time.time() - start, 2)
    score = round(ok_count / total_rows * 100, 2) if total_rows else 0.0

    # Store context so the frontend can request an AI summary later
    result_id = str(uuid.uuid4())
    _store_summary_context(result_id, {
        "matched": ok_count,
        "mismatched": ecart_count,
        "pdf_only": missing_pdf,
        "csv_only": 0,
        "score": score,
        "details": [r for r in all_rows if r["Statut"] not in ("OK", "PDF non disponible (pas de LEI)")],
        "pdf_only_details": [],
        "csv_only_details": [],
    })

    return {
        "id": result_id,
        "date": datetime.now().isoformat(),
        "report_date": report_date,
        "output_file": out_filename,
        "excel_file": req.excel_file,
        "complianceScore": score,
        "summary": {
            "matched": ok_count,
            "ecart": ecart_count,
            "pdfOnly": missing_pdf,
            "csvOnly": 0,
            "total": total_rows,
        },
        "bank_results": bank_results,
        "skipped_banks": skipped_banks,
        "transactions": all_rows,
        "aiSynthesis": "",
        "processingTime": elapsed,
        "pdfFile": {"id": "batch", "name": f"{len(req.zip_files)} ZIP files", "size": 0, "type": "pdf"},
        "csvFile": {"id": "excel", "name": req.excel_file, "size": int(excel_path.stat().st_size), "type": "csv"},
    }


# ─── /api/summary — on-demand AI synthesis ───────────────────────────────────
@app.post("/api/summary")
def generate_summary(req: SummaryRequest):
    """
    Generate an AI synthesis for a previously run reconciliation.
    The context is stored in memory during the session; call this only when
    the user explicitly clicks the "Generate Summary" button in the UI.
    """
    ctx = _SUMMARY_CONTEXTS.get(req.result_id)
    if ctx is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Contexte introuvable. Relancez le rapprochement."},
        )
    synthesis = summarize_reconciliation(ctx)
    return {"aiSynthesis": synthesis}


# ─── /compare (legacy single-file upload) ────────────────────────────────────
@app.post("/compare")
async def compare(
    pdf: UploadFile = File(...),
    csv: UploadFile = File(...),
    use_ai: bool = True,
    method: str = "rule",
):
    pdf_path = f"uploads/{pdf.filename}"
    csv_path = f"uploads/{csv.filename}"

    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)
    with open(csv_path, "wb") as buffer:
        shutil.copyfileobj(csv.file, buffer)

    start = time.time()

    try:
        spreadsheet_df = read_flexible_csv(csv_path)

        first_column = str(spreadsheet_df.columns[0]).strip().lower() if len(spreadsheet_df.columns) else ""

        if first_column in {"métrique", "metrique", "metric"} or first_column not in {"date", "référence", "reference"}:
            pdf_transactions = await run_in_threadpool(extract_bank_metrics, pdf_path)
            result = compare_transactions(pdf_transactions, spreadsheet_df, pdf_name=pdf.filename)
        elif method == "ai":
            from services.pdf_parser import extract_transactions_ai
            pdf_transactions = await run_in_threadpool(extract_transactions_ai, pdf_path)
            result = compare_transactions(pdf_transactions, spreadsheet_df, pdf_name=pdf.filename)
        else:
            pdf_transactions = await run_in_threadpool(extract_transactions, pdf_path)
            result = compare_transactions(pdf_transactions, spreadsheet_df, pdf_name=pdf.filename)

    except Exception as e:
        return {"error": f"Erreur lecture PDF : {str(e)}"}

    if "error" in result:
        return {"error": result["error"]}

    ai_synthesis = summarize_reconciliation(result) if use_ai else ""

    transactions = result.get("transactions", [])
    processing_time = round(time.time() - start, 2)

    return {
        "id": str(uuid.uuid4()),
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pdfFile": {"id": "pdf", "name": pdf.filename, "size": os.path.getsize(pdf_path), "type": "pdf"},
        "csvFile": {"id": "csv", "name": csv.filename, "size": os.path.getsize(csv_path), "type": "csv"},
        "complianceScore": result.get("score", 0.0),
        "summary": {
            "matched": result.get("matched", 0),
            "ecart": result.get("mismatched", 0),
            "pdfOnly": result.get("pdf_only", 0),
            "csvOnly": result.get("csv_only", 0),
            "total": len(transactions),
        },
        "transactions": transactions,
        "aiSynthesis": ai_synthesis,
        "processingTime": processing_time,
    }
