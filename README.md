# Concilio Demo Runbook

This repo is a local banking reconciliation demo. For the meeting, the safest path is the single-bank comparison flow:

- one official bank PDF from `UBpartner/`
- one comparison workbook from the workspace root
- one output showing the per-indicator reconciliation table plus the AI summary

## What to use for the demo

Use these files first:

- PDF: `UBpartner/bpce-pillar-iii-2024-report-update-june-2025.pdf`
- Internal results workbook: `Comparaison_banques_2025-12-31 (1).xlsx`

The file `Comparaison_EBA_vs_resultats_2025-12-31.xlsx` is the target output example from the manager. It is not an input.

The app expects the internal-results workbook plus the PDF, then writes a final Excel comparison that looks like the manager's example.

## What the app does now

The backend accepts a PDF plus the internal results spreadsheet and tries to reconcile them.

- If the spreadsheet has a `Métrique` column and bank-name columns, it uses the metric comparison path.
- If the spreadsheet already looks like the final comparison output, the app will reject it and tell you to use the internal workbook instead.
- AI is used for the summary step, not for the final numeric truth.

## How to run it

1. Start the backend.

   ```powershell
   Set-Location 'e:/00 AI WORK/backend'
   ..\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ..\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8000
   ```

2. Start the frontend.

   ```powershell
   Set-Location 'e:/00 AI WORK/frontend'
   npm install
   npm run dev
   ```

3. Open the frontend in the browser.

4. Upload the PDF and the internal results workbook.

5. Click the analyze button and wait for the result screen.

## What to expect in the demo

You should see:

- a processing screen
- a results view with the comparison score
- a table of rows and statuses
- a short AI-generated French summary
- a downloadable Excel comparison file with the manager-style columns

For the meeting, the most important thing is that the output looks like a structured reconciliation report, not that every possible bank case is solved.

## Quick test right now

If you want a fast verification without the UI, run the backend logic against the shared files from Python and confirm that it loads the workbook and PDF without errors.

Expected outcome:

- the workbook opens
- the PDF text is readable
- the app returns a comparison object
- the frontend build succeeds

## Known gaps

- Full RAG is not implemented yet.
- The PDF metric extractor is still a practical demo path, not a fully bank-agnostic production parser.
- The current demo is tuned for the BPCE single-bank case and the internal workbook format from the shared folder.

## Next steps after the meeting

1. Add a real RAG layer for page retrieval and bank/indicator lookup.
2. Normalize arbitrary internal Excel files into the same long comparison schema.
3. Make the bank selection explicit so one upload can be compared against many bank PDFs.
4. Cache OCR/text extraction so repeated runs stay fast.
