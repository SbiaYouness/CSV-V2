import { useState, useEffect, useCallback } from 'react';
import { AppState, ReconciliationResult, ProcessingStep } from './types';
import { HistorySidebar } from './components/HistorySidebar';
import { UploadWorkspace } from './components/UploadWorkspace';
import { ProcessingView } from './components/ProcessingView';
import { ResultsView } from './components/ResultsView';
import * as XLSX from 'xlsx';

const API = '';
const HISTORY_KEY = 'concilio_analysis_history';

const PROCESSING_STEPS: ProcessingStep[] = [
  'extraction_zip',
  'extraction_pdf',
  'lecture_excel',
  'correspondance',
  'anomalies',
  'rapport_ia',
];

const STEP_DURATIONS: number[] = [1500, 2500, 1500, 2000, 2000, 999999];

function loadHistory(): ReconciliationResult[] {
  try {
    const stored = localStorage.getItem(HISTORY_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveHistory(history: ReconciliationResult[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  } catch {
    console.error('Erreur sauvegarde historique');
  }
}

export default function App() {
  const [history, setHistory] = useState<ReconciliationResult[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [selectedHistoryId, setSelectedHistoryId] = useState<string | null>(null);
  const [appState, setAppState] = useState<AppState>({ type: 'upload' });

  useEffect(() => {
    setHistory(loadHistory());
    setHistoryLoaded(true);
  }, []);

  useEffect(() => {
    if (historyLoaded) saveHistory(history);
  }, [history, historyLoaded]);

  const handleAnalyze = useCallback(
    async (excelFile: string, zipFiles: string[], reportDate: string, useAIExtraction: boolean) => {
      let stepIndex = 0;

      setAppState({
        type: 'processing',
        processing: { currentStep: PROCESSING_STEPS[0], completedSteps: [] },
      });

      const advanceStep = () => {
        stepIndex++;
        if (stepIndex < PROCESSING_STEPS.length) {
          setAppState({
            type: 'processing',
            processing: {
              currentStep: PROCESSING_STEPS[stepIndex],
              completedSteps: PROCESSING_STEPS.slice(0, stepIndex),
            },
          });
          if (stepIndex < PROCESSING_STEPS.length - 1) {
            setTimeout(advanceStep, STEP_DURATIONS[stepIndex]);
          }
        }
      };

      setTimeout(advanceStep, STEP_DURATIONS[0]);

      try {
        const response = await fetch(`${API}/api/reconcile`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ excel_file: excelFile, zip_files: zipFiles, report_date: reportDate, use_ai_extraction: useAIExtraction }),
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.error || 'Reconciliation failed');
        }

        const result: ReconciliationResult = await response.json();
        setHistory((prev) => [result, ...prev].slice(0, 20));
        setSelectedHistoryId(result.id);
        setAppState({ type: 'results', result });
      } catch (error) {
        console.error('Reconciliation failed:', error);
        setAppState({ type: 'upload' });
        alert(`Erreur: ${error instanceof Error ? error.message : 'Erreur inconnue'}`);
      }
    },
    []
  );

  const handleHistorySelect = useCallback((result: ReconciliationResult) => {
    setSelectedHistoryId(result.id);
    setAppState({ type: 'results', result });
  }, []);

  const handleBack = useCallback(() => {
    setSelectedHistoryId(null);
    setAppState({ type: 'upload' });
  }, []);

  const handleDownload = useCallback(() => {
    if (appState.type !== 'results') return;
    const result = appState.result;

    // Map transactions → plain row objects
    const rows = result.transactions.map((tx) => ({
      Entité: tx.Entité ?? tx.entity ?? '',
      LEI: tx.LEI ?? tx.lei ?? '',
      Indicateur: tx.Indicateur ?? tx.indicator ?? tx.reference ?? '',
      'Valeur resultats': tx['Valeur resultats'] ?? tx.resultValue ?? tx.csvAmount ?? null,
      'Valeur PDF (EBA)': tx['Valeur PDF (EBA)'] ?? tx.pdfValue ?? tx.pdfAmount ?? null,
      Ecart: tx.Ecart ?? tx.difference ?? null,
      'Ecart %': tx['Ecart %'] ?? null,
      Statut: tx.Statut ?? (tx.status === 'matched' ? 'OK' : 'ECART SIGNIFICATIF'),
      'Source PDF': tx['Source PDF'] ?? tx.sourcePdf ?? '',
    }));

    const workbook = XLSX.utils.book_new();
    const worksheet = XLSX.utils.json_to_sheet(rows);

    // ── Column widths ──────────────────────────────────────────────────────────
    worksheet['!cols'] = [
      { wch: 28 },  // Entité
      { wch: 22 },  // LEI
      { wch: 16 },  // Indicateur
      { wch: 18 },  // Valeur resultats
      { wch: 18 },  // Valeur PDF (EBA)
      { wch: 14 },  // Ecart
      { wch: 10 },  // Ecart %
      { wch: 28 },  // Statut
      { wch: 32 },  // Source PDF
    ];

    // ── Header style ───────────────────────────────────────────────────────────
    const headerStyle = {
      fill: { fgColor: { rgb: '1E293B' } },   // slate-800
      font: { bold: true, color: { rgb: 'CBD5E1' } },
      alignment: { horizontal: 'center' },
    };
    const headers = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I'];
    headers.forEach((col) => {
      const cell = worksheet[`${col}1`];
      if (cell) cell.s = headerStyle;
    });

    // ── Row highlighting ───────────────────────────────────────────────────────
    // Red fill for ECART SIGNIFICATIF / ANOMALIE rows, light green for OK
    rows.forEach((row, rowIdx) => {
      const excelRow = rowIdx + 2;  // 1-indexed + header row
      const statut: string = row.Statut ?? '';
      const isBigGap = statut.includes('ECART SIGNIFICATIF') || statut.includes('ANOMALIE UNITE');
      const isOk = statut === 'OK';

      if (!isBigGap && !isOk) return;

      const bgRgb = isBigGap ? '4C0519' : '052E16';   // rose-950 / green-950
      const fontRgb = isBigGap ? 'FECDD3' : 'BBF7D0'; // rose-200 / green-200
      const cellStyle = {
        fill: { fgColor: { rgb: bgRgb } },
        font: { color: { rgb: fontRgb }, bold: isBigGap },
      };
      headers.forEach((col) => {
        const addr = `${col}${excelRow}`;
        const cell = worksheet[addr];
        if (cell) cell.s = cellStyle;
      });
    });

    XLSX.utils.book_append_sheet(workbook, worksheet, 'Comparaison');

    // ── Summary sheet ──────────────────────────────────────────────────────────
    const summarySheet = XLSX.utils.json_to_sheet([
      { Indicateur: 'Score de conformité', Valeur: result.complianceScore },
      { Indicateur: 'Correspondances', Valeur: result.summary.matched },
      { Indicateur: 'Écarts', Valeur: result.summary.ecart },
      { Indicateur: 'PDF uniquement', Valeur: result.summary.pdfOnly },
      { Indicateur: 'Total', Valeur: result.summary.total },
      { Indicateur: 'Synthèse IA', Valeur: result.aiSynthesis ?? '(non générée)' },
    ]);
    XLSX.utils.book_append_sheet(workbook, summarySheet, 'Résumé');

    const output = XLSX.write(workbook, { bookType: 'xlsx', type: 'array', cellStyles: true });
    const blob = new Blob([output], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const date = result.report_date ?? new Date().toISOString().split('T')[0];
    link.download = result.output_file ?? `Comparaison_EBA_vs_resultats_${date}.xlsx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [appState]);


  const renderWorkspace = () => {
    switch (appState.type) {
      case 'upload':
        return <UploadWorkspace onAnalyze={handleAnalyze} />;
      case 'processing':
        return <ProcessingView state={appState.processing} />;
      case 'results':
        return <ResultsView result={appState.result} onDownload={handleDownload} onBack={handleBack} />;
    }
  };

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <HistorySidebar
        history={history}
        selectedId={selectedHistoryId}
        onSelect={handleHistorySelect}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
      />
      <main className="flex-1 overflow-hidden">
        {renderWorkspace()}
      </main>
    </div>
  );
}
