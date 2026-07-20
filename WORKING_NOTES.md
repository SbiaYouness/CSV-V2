# Working Notes

## Goal

Deliver a single-bank demo fast, with a path to scale to many PDFs later.

## Current logic

- Backend entry point: `backend/app.py`
- Spreadsheet reader: `backend/services/csv_parser.py`
- PDF metric extraction: `backend/services/pdf_parser.py`
- Comparison logic: `backend/services/comparator.py`
- AI summary: `backend/services/llm.py`

## Demo flow

1. Upload one official bank PDF.
2. Upload the internal results workbook, not the final comparison output file.
3. Compare the bank metrics row by row.
4. Show a score, anomaly counts, a French summary, and a downloadable Excel report.

## What AI should do

- Summarize the comparison.
- Help with ambiguous label matching if needed.
- Help later with RAG page retrieval across many PDFs.

## What should stay deterministic

- Numeric extraction.
- Percentage and unit conversion.
- Final comparison and status assignment.

## Short-term priority

- Keep the meeting demo stable.
- Avoid adding slow model calls in the core comparison path.
- Treat RAG as the next phase, not the blocker for today.

## Files to touch next

- `backend/services/pdf_parser.py` for stronger page targeting.
- `backend/services/comparator.py` for better status classification.
- `frontend/src/App.tsx` for any workbook export polish.
- `frontend/src/components/UploadWorkspace.tsx` if the upload labels need to match the final demo wording.
- `frontend/src/components/ResultsView.tsx` if the final table should show bank metrics instead of transaction-style columns.
