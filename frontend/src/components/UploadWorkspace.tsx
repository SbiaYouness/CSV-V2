import { useCallback, useEffect, useMemo, useState } from 'react';
import { AvailableFiles, ZipFileEntry, ExcelFileEntry } from '../types';

const API = '';

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / 1024 / 1024).toFixed(2)} Mo`;
}

interface Props {
  onAnalyze: (excelFile: string, zipFiles: string[], reportDate: string, useAIExtraction: boolean) => void;
}

export function UploadWorkspace({ onAnalyze }: Props) {
  const [files, setFiles] = useState<AvailableFiles | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [selectedExcel, setSelectedExcel] = useState<string>('');
  const [checkedZips, setCheckedZips] = useState<Set<string>>(new Set());
  const [activeDate, setActiveDate] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [useAIExtraction, setUseAIExtraction] = useState(false);

  // Fetch available files from backend
  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/files`)
      .then((r) => {
        if (!r.ok) {
          throw new Error(`Erreur du serveur (Statut ${r.status})`);
        }
        return r.json();
      })
      .then((data: AvailableFiles) => {
        if (!data || !data.excel_files || !data.by_date) {
          throw new Error("Format de données invalide reçu du serveur.");
        }
        setFiles(data);
        // Auto-select first Excel only if there's exactly one (unambiguous)
        if (data.excel_files.length === 1) setSelectedExcel(data.excel_files[0].name);
        
        // Auto-check all available ZIPs by default and display the 'all' tab initially
        setActiveDate('all');
        const allZipNames = data.zip_files.map((z: ZipFileEntry) => z.name);
        setCheckedZips(new Set(allZipNames));
        
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Impossible de joindre le backend. Vérifiez que le serveur est en cours d'exécution.");
        setLoading(false);
      });
  }, []);

  const dates = useMemo(() => {
    if (!files || !files.by_date) return [];
    return Object.keys(files.by_date).sort().reverse();
  }, [files]);

  // Zips filtered by active date tab
  const dateFilteredZips: ZipFileEntry[] = useMemo(() => {
    if (!files) return [];
    if (activeDate === 'all') return files.zip_files || [];
    return (files.by_date && files.by_date[activeDate]) ?? [];
  }, [files, activeDate]);

  // Further filtered by search text (matches name or LEI, case-insensitive)
  const visibleZips: ZipFileEntry[] = useMemo(() => {
    if (!search.trim()) return dateFilteredZips;
    const q = search.toLowerCase();
    return dateFilteredZips.filter(
      (z) => z.name.toLowerCase().includes(q) || z.lei.toLowerCase().includes(q)
    );
  }, [dateFilteredZips, search]);

  // Derived: how many of the visible zips are checked
  const visibleCheckedCount = visibleZips.filter((z) => checkedZips.has(z.name)).length;
  const allVisibleChecked = visibleZips.length > 0 && visibleCheckedCount === visibleZips.length;
  const someVisibleChecked = visibleCheckedCount > 0 && !allVisibleChecked;
  const totalSelected = checkedZips.size;
  const totalZips = files?.zip_files.length ?? 0;

  const toggleAll = useCallback(() => {
    setCheckedZips((prev) => {
      const next = new Set(prev);
      if (allVisibleChecked) {
        visibleZips.forEach((z) => next.delete(z.name));
      } else {
        visibleZips.forEach((z) => next.add(z.name));
      }
      return next;
    });
  }, [allVisibleChecked, visibleZips]);

  const clearAll = useCallback(() => {
    setCheckedZips(new Set());
  }, []);

  const toggleZip = useCallback((name: string) => {
    setCheckedZips((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  // Keyboard handler for zip rows
  const handleZipKeyDown = useCallback(
    (e: React.KeyboardEvent, name: string) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleZip(name);
      }
    },
    [toggleZip]
  );

  // Derive report date from selected zips (first date found) or active date tab
  const reportDate = useMemo(() => {
    if (activeDate !== 'all') return activeDate;
    for (const name of checkedZips) {
      const zip = files?.zip_files.find((z) => z.name === name);
      if (zip?.date) return zip.date;
    }
    return '';
  }, [checkedZips, activeDate, files]);

  const canAnalyze = selectedExcel !== '' && checkedZips.size > 0;

  // Contextual message for the run button
  const runButtonLabel = (): string => {
    if (selectedExcel === '' && checkedZips.size === 0) return 'Sélectionnez une banque et un classeur';
    if (checkedZips.size === 0) return 'Sélectionnez au moins une banque';
    if (selectedExcel === '') return 'Sélectionnez un classeur Excel';
    return 'Lancer le rapprochement';
  };

  const handleAnalyze = () => {
    if (!canAnalyze) return;
    onAnalyze(selectedExcel, Array.from(checkedZips), reportDate, useAIExtraction);
  };

  // ── Render ────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-10 h-10 border-2 border-gold border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-gray-400 text-sm">Chargement des fichiers disponibles…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-screen flex items-center justify-center p-8">
        <div className="max-w-md text-center space-y-4">
          <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center mx-auto">
            <svg className="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
          </div>
          <p className="text-gray-300 font-medium">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-gray-200 text-sm transition-colors"
          >
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col p-6 overflow-hidden">
      {/* Header */}
      <div className="mb-5 flex-shrink-0">
        <h1 className="text-xl font-semibold text-gray-100">Rapprochement Pilier 3 EBA</h1>
        <p className="text-gray-500 text-sm mt-1">
          Recherchez et sélectionnez les banques à analyser, puis choisissez le classeur de résultats.
        </p>
      </div>

      {/* Main two-column grid */}
      <div className="flex gap-4 flex-1 min-h-0">

        {/* ── Left: PDF ZIPs ───────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col bg-background-lighter border border-slate-700/60 rounded-xl overflow-hidden">

          {/* Panel header: search + date tabs */}
          <div className="px-4 pt-3 pb-2 border-b border-slate-700/60 flex-shrink-0 space-y-2">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-red-400 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
              </svg>
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Rapports PDF (ZIP)</span>
            </div>

            {/* Search input */}
            <div className="relative">
              <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher par nom ou LEI…"
                className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-background-elevated border border-slate-700 text-sm text-gray-300 placeholder-gray-600 focus:outline-none focus:border-slate-500 focus:ring-1 focus:ring-slate-500/50 transition-colors"
                aria-label="Rechercher une banque"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition-colors"
                  aria-label="Effacer la recherche"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>

            {/* Date quick-filter tabs */}
            {dates.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                <button
                  onClick={() => setActiveDate('all')}
                  className={`px-2.5 py-1 rounded text-xs font-mono-numbers transition-colors
                    ${activeDate === 'all' ? 'bg-gold/20 text-gold border border-gold/30' : 'text-gray-500 hover:text-gray-300 border border-transparent hover:border-slate-700'}`}
                >
                  Tous
                </button>
                {dates.map((d) => (
                  <button
                    key={d}
                    onClick={() => setActiveDate(d)}
                    className={`px-2.5 py-1 rounded text-xs font-mono-numbers transition-colors
                      ${activeDate === d ? 'bg-gold/20 text-gold border border-gold/30' : 'text-gray-500 hover:text-gray-300 border border-transparent hover:border-slate-700'}`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            )}

            {/* Bulk action bar */}
            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-3">
                {/* Select all visible toggle */}
                <button
                  onClick={toggleAll}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleAll(); }}}
                  className="flex items-center gap-2 cursor-pointer group focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50 rounded"
                  aria-label={allVisibleChecked ? 'Tout désélectionner' : 'Tout sélectionner'}
                  aria-pressed={allVisibleChecked}
                >
                  <div
                    className={`w-4 h-4 rounded border flex items-center justify-center transition-colors
                      ${allVisibleChecked ? 'bg-gold border-gold' : someVisibleChecked ? 'bg-gold/40 border-gold/40' : 'border-slate-600 group-hover:border-slate-400'}`}
                  >
                    {allVisibleChecked && (
                      <svg className="w-2.5 h-2.5 text-background" fill="none" viewBox="0 0 12 12" stroke="currentColor" strokeWidth={2.5}>
                        <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                    {someVisibleChecked && !allVisibleChecked && (
                      <div className="w-2 h-0.5 bg-background rounded" />
                    )}
                  </div>
                  <span className="text-xs text-gray-500 group-hover:text-gray-300 transition-colors">
                    {allVisibleChecked ? 'Tout désélectionner' : `Tout sélectionner (${visibleZips.length})`}
                  </span>
                </button>

                {/* Clear selection */}
                {totalSelected > 0 && (
                  <button
                    onClick={clearAll}
                    className="text-xs text-gray-600 hover:text-red-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400/50 rounded px-1"
                  >
                    Effacer la sélection
                  </button>
                )}
              </div>

              {/* Live selection counter */}
              <div className="flex items-center gap-1.5">
                {totalSelected > 0 ? (
                  <span className="text-xs font-mono-numbers">
                    <span className="text-gold font-semibold">{totalSelected}</span>
                    <span className="text-gray-600">/{totalZips} sélectionné{totalSelected > 1 ? 's' : ''}</span>
                  </span>
                ) : (
                  <span className="text-xs text-gray-700">Aucune banque sélectionnée</span>
                )}
              </div>
            </div>
          </div>

          {/* ZIP list */}
          <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {visibleZips.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full py-12 text-center">
                <svg className="w-8 h-8 text-gray-700 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-gray-600 text-sm">
                  {search ? `Aucun résultat pour « ${search} »` : 'Aucun fichier ZIP trouvé.'}
                </p>
                {search && (
                  <button onClick={() => setSearch('')} className="mt-2 text-xs text-gray-500 hover:text-gray-300 underline transition-colors">
                    Effacer la recherche
                  </button>
                )}
              </div>
            ) : (
              visibleZips.map((zip) => {
                const checked = checkedZips.has(zip.name);
                return (
                  <div
                    key={zip.name}
                    role="checkbox"
                    aria-checked={checked}
                    tabIndex={0}
                    onClick={() => toggleZip(zip.name)}
                    onKeyDown={(e) => handleZipKeyDown(e, zip.name)}
                    className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors group
                      focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50
                      ${checked ? 'bg-gold/5 border border-gold/20' : 'border border-transparent hover:bg-slate-800/60'}`}
                  >
                    {/* Checkbox */}
                    <div
                      className={`mt-0.5 w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center transition-colors
                        ${checked ? 'bg-gold border-gold' : 'border-slate-600 group-hover:border-slate-400'}`}
                    >
                      {checked && (
                        <svg className="w-2.5 h-2.5 text-background" fill="none" viewBox="0 0 12 12" stroke="currentColor" strokeWidth={2.5}>
                          <path d="M2 6l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-gray-300 font-mono truncate">{zip.name}</div>
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-xs text-gray-600 font-mono-numbers">{zip.lei}</span>
                        <span className="text-xs text-gray-700">{formatSize(zip.size)}</span>
                        {zip.date && (
                          <span className="text-xs bg-slate-800 text-gray-500 px-1.5 py-0.5 rounded font-mono-numbers">{zip.date}</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* ── Right: Excel files ───────────────────────────────────────────── */}
        <div className="w-80 flex flex-col bg-background-lighter border border-slate-700/60 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/60 flex-shrink-0">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L7.414 8A2 2 0 0110.586 10H16v6a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
              </svg>
              <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Classeur de résultats</span>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {(files?.excel_files ?? []).length === 0 ? (
              <p className="text-center text-gray-600 text-sm py-10">Aucun classeur Excel trouvé.</p>
            ) : (
              (files?.excel_files ?? []).map((xls: ExcelFileEntry) => {
                const selected = selectedExcel === xls.name;
                return (
                  <div
                    key={xls.name}
                    role="radio"
                    aria-checked={selected}
                    tabIndex={0}
                    onClick={() => setSelectedExcel(xls.name)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedExcel(xls.name);
                      }
                    }}
                    className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors group
                      focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/50
                      ${selected ? 'bg-emerald-500/10 border border-emerald-500/30' : 'border border-transparent hover:bg-slate-800/60'}`}
                  >
                    {/* Radio */}
                    <div className={`mt-0.5 w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center transition-colors
                      ${selected ? 'border-emerald-400' : 'border-slate-600 group-hover:border-slate-400'}`}>
                      {selected && <div className="w-2 h-2 rounded-full bg-emerald-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-gray-300 font-mono truncate">{xls.name}</div>
                      <div className="text-xs text-gray-600 mt-0.5 font-mono-numbers">{formatSize(xls.size)}</div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Footer: summary + analyze button */}
      <div className="mt-4 flex items-center justify-between flex-shrink-0 gap-4">
        <div className="text-xs text-gray-600 min-w-0 flex-1 flex items-center gap-4">
          {canAnalyze ? (
            <span>
              <span className="text-gold font-mono-numbers font-semibold">{checkedZips.size}</span>
              <span className="text-gray-500"> ZIP{checkedZips.size > 1 ? 's' : ''} · </span>
              <span className="text-emerald-400/80 font-mono truncate">{selectedExcel}</span>
              {reportDate && (
                <span className="text-gray-600"> · {reportDate}</span>
              )}
            </span>
          ) : (
            <span className="text-gray-700 italic">{runButtonLabel()}</span>
          )}
          
          {canAnalyze && (
            <label className="flex items-center gap-2 cursor-pointer group px-3 py-1.5 rounded bg-slate-800/50 hover:bg-slate-800 transition-colors border border-slate-700/50">
              <input
                type="checkbox"
                className="w-4 h-4 rounded border-gray-600 text-gold focus:ring-gold focus:ring-offset-background bg-slate-900"
                checked={useAIExtraction}
                onChange={(e) => setUseAIExtraction(e.target.checked)}
              />
              <span className="text-sm font-medium text-gray-300 group-hover:text-gold transition-colors">
                Activer l'extraction AI (Ollama VL)
              </span>
            </label>
          )}
        </div>
        <button
          id="run-analysis-btn"
          onClick={handleAnalyze}
          disabled={!canAnalyze}
          aria-disabled={!canAnalyze}
          className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-medium text-sm transition-all duration-200 flex-shrink-0
            ${canAnalyze
              ? 'bg-gold hover:bg-gold-bright text-background shadow-lg shadow-gold/20 cursor-pointer'
              : 'bg-slate-800 text-gray-600 cursor-not-allowed'}`}
        >
          {canAnalyze ? (
            <>
              Lancer le rapprochement
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
              </svg>
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              {runButtonLabel()}
            </>
          )}
        </button>
      </div>
    </div>
  );
}
