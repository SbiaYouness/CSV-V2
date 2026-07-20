import { useEffect, useMemo, useState, useCallback } from 'react';
import { ReconciliationResult, Transaction, BankResult } from '../types';

interface ResultsViewProps {
  result: ReconciliationResult;
  onDownload: () => void;
  onBack: () => void;
}

const API = '';

// ── Color scale (0%=red, 1–50%=amber, >50%=green, no PDF=gray) ───────────────
function getScoreColors(score: number, hasPdf: boolean) {
  if (!hasPdf) return { text: 'text-gray-500', bg: 'bg-slate-800/60', border: 'border-slate-800' };
  if (score === 0) return { text: 'text-red-400', bg: 'bg-red-900/20', border: 'border-red-700/40' };
  if (score <= 50) return { text: 'text-amber-400', bg: 'bg-amber-900/20', border: 'border-amber-700/40' };
  return { text: 'text-emerald-400', bg: 'bg-emerald-900/20', border: 'border-emerald-700/40' };
}

const STATUT_CONFIG: Record<string, { label: string; color: string; bgColor: string }> = {
  'OK': { label: 'OK', color: 'text-emerald-400', bgColor: 'bg-emerald-900/20' },
  'ECART SIGNIFICATIF': { label: 'Écart', color: 'text-red-400', bgColor: 'bg-red-900/30' },
  'Non trouvé dans le PDF': { label: 'Absent PDF', color: 'text-blue-400', bgColor: 'bg-blue-900/20' },
  'Absent du fichier resultats': { label: 'Absent résultats', color: 'text-purple-400', bgColor: 'bg-purple-900/20' },
  'PDF non disponible': { label: 'Pas de PDF', color: 'text-gray-500', bgColor: 'bg-slate-800/60' },
  'Données consolidées au niveau parent': { label: 'Consolidé parent', color: 'text-indigo-300', bgColor: 'bg-indigo-900/20' },
  'ANOMALIE UNITE PROBABLE (facteur ~100, fichier resultats)': { label: 'Unité x100', color: 'text-orange-400', bgColor: 'bg-orange-900/20' },
};

function getStatutConfig(statut: string | undefined) {
  if (!statut) return { label: '—', color: 'text-gray-500', bgColor: 'bg-transparent' };
  for (const [key, cfg] of Object.entries(STATUT_CONFIG)) {
    if (statut.includes(key)) return cfg;
  }
  return { label: statut, color: 'text-gray-400', bgColor: 'bg-slate-800' };
}

/** True when the row has a significant numeric discrepancy */
function isSignificantGap(tx: Transaction): boolean {
  const statut = tx.Statut ?? '';
  return statut.includes('ECART SIGNIFICATIF') || statut.includes('ANOMALIE UNITE PROBABLE');
}

function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  if (abs === 0) return '0';
  if (abs < 1) return (v * 100).toFixed(2) + '%';
  if (abs >= 1e9) return (v / 1e9).toFixed(3) + ' Mrd';
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + ' M€';
  if (abs >= 1e3) return new Intl.NumberFormat('fr-FR').format(v);
  return v.toFixed(4);
}

// ── AnimatedScore ─────────────────────────────────────────────────────────────
function AnimatedScore({ score }: { score: number }) {
  const [display, setDisplay] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const animate = () => {
      const p = Math.min((Date.now() - start) / 900, 1);
      setDisplay(Math.round(score * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }, [score]);

  const color = score >= 80 ? 'text-emerald-400' : score >= 50 ? 'text-amber-400' : 'text-red-400';
  return <span className={`font-mono-numbers text-5xl font-bold ${color}`}>{display}%</span>;
}

// ── Bank category helpers ─────────────────────────────────────────────────────
function bankCategory(b: BankResult): { noPdf: boolean; noData: boolean } {
  const noPdf = !b.has_pdf;
  const noData = b.has_pdf && (b.input_metrics === 0 || b.total === 0);
  return { noPdf, noData };
}

function bankKey(bank: BankResult, index: number): string {
  return bank.id ?? `${bank.lei || bank.bank}:${index}`;
}

function isSelectedBankRow(transaction: Transaction, bank: BankResult | null): boolean {
  if (!bank) return true;
  if (bank.id && transaction.bank_id) return bank.id === transaction.bank_id;
  return transaction['Entité']?.trim() === bank.bank.trim();
}

// ── BankScoreGrid ─────────────────────────────────────────────────────────────
function BankScoreGrid({
  banks,
  selectedBankKey,
  onSelectBank,
}: {
  banks: BankResult[];
  selectedBankKey: string | null;
  onSelectBank: (bankKey: string | null) => void;
}) {
  if (banks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center bg-background-lighter rounded-xl border border-slate-800">
        <svg className="w-8 h-8 text-gray-700 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-gray-600 text-sm">Aucune banque ne correspond à ces filtres.</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
      {banks.map((b, i) => {
        const { noPdf, noData } = bankCategory(b);
        const colors = getScoreColors(b.score, b.has_pdf);
        const key = bankKey(b, i);
        const selected = selectedBankKey === key;

        return (
          <div
            key={`${b.lei || b.bank}-${i}`}
            className={`p-3 rounded-lg border bg-background-lighter transition-all ${colors.border} ${selected ? 'ring-2 ring-gold/60 ring-offset-1 ring-offset-background' : ''}`}
          >
            <div className="text-xs text-gray-400 truncate mb-1" title={b.bank}>{b.bank}</div>
            <div className={`font-mono-numbers text-lg font-semibold ${colors.text}`}>
              {noPdf ? '—' : noData ? '—' : `${b.score}%`}
            </div>
            <div className="text-xs text-gray-600 font-mono-numbers mt-0.5">
              {noPdf
                ? b.reports_with_parent ? `Consolidé : ${b.parent_group}` : 'Pas de PDF'
                : noData ? 'Aucune donnée' : `${b.matched}/${b.total} validés`}
            </div>
            {!noPdf && !noData && b.pdf_metrics_found !== undefined && (
              <div className="text-[10px] text-gray-600 font-mono-numbers mt-0.5">
                PDF : {b.pdf_metrics_found}/{b.expected_metrics ?? b.total} trouvés
              </div>
            )}
            <button
              type="button"
              id={`bank-detail-btn-${(b.lei || b.bank).replace(/\s+/g, '-')}-${i}`}
              tabIndex={0}
              onClick={() => onSelectBank(selected ? null : key)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectBank(selected ? null : key);
                }
              }}
              className={`mt-2 w-full rounded-md border px-2 py-1 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50
                ${selected
                  ? 'border-gold/50 text-gold bg-gold/5 hover:bg-gold/10'
                  : 'border-slate-700 text-gray-400 hover:border-gold/50 hover:text-gray-200'
                }`}
            >
              {selected ? 'Fermer' : 'Voir données'}
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── ResultsFilterBar ──────────────────────────────────────────────────────────
type StatusFilter = 'has_pdf' | 'no_pdf';
type MatchRateFilter = 'zero' | 'above_zero' | 'above_fifty' | 'hundred';

interface ActiveFilters {
  status: Set<StatusFilter>;
  matchRate: MatchRateFilter | null;
}

function matchesBankFilters(b: BankResult, filters: ActiveFilters): boolean {
  const { noPdf } = bankCategory(b);
  const hasStatusFilter = filters.status.size > 0;
  const hasMatchFilter = filters.matchRate !== null;

  if (!hasStatusFilter && !hasMatchFilter) return true;

  let statusMatch = false;
  if (filters.status.has('has_pdf') && !noPdf) statusMatch = true;
  if (filters.status.has('no_pdf') && noPdf) statusMatch = true;

  let matchRateMatch = false;
  if (filters.matchRate === 'zero') matchRateMatch = b.has_pdf && b.total > 0 && b.score === 0;
  if (filters.matchRate === 'above_zero') matchRateMatch = b.has_pdf && b.total > 0 && b.score > 0;
  if (filters.matchRate === 'above_fifty') matchRateMatch = b.has_pdf && b.total > 0 && b.score > 50;
  if (filters.matchRate === 'hundred') matchRateMatch = b.has_pdf && b.total > 0 && b.score === 100;

  if (hasStatusFilter && hasMatchFilter) return statusMatch && matchRateMatch;
  if (hasStatusFilter) return statusMatch;
  if (hasMatchFilter) return matchRateMatch;
  return true;
}

function ResultsFilterBar({
  banks,
  filters,
  onChange,
  onReset,
}: {
  banks: BankResult[];
  filters: ActiveFilters;
  onChange: (filters: ActiveFilters) => void;
  onReset: () => void;
}) {
  const hasAnyFilter = filters.status.size > 0 || filters.matchRate !== null;

  const counts = useMemo(() => {
    return {
      has_pdf: banks.filter((b) => b.has_pdf).length,
      no_pdf: banks.filter((b) => !b.has_pdf).length,
      zero: banks.filter((b) => b.has_pdf && b.total > 0 && b.score === 0).length,
      above_zero: banks.filter((b) => b.has_pdf && b.total > 0 && b.score > 0).length,
      above_fifty: banks.filter((b) => b.has_pdf && b.total > 0 && b.score > 50).length,
      hundred: banks.filter((b) => b.has_pdf && b.total > 0 && b.score === 100).length,
    };
  }, [banks]);

  const toggleStatus = (chip: StatusFilter) => {
    const next = new Set(filters.status);
    if (next.has(chip)) next.delete(chip);
    else next.add(chip);
    onChange({ ...filters, status: next });
  };

  const setMatchRate = (chip: MatchRateFilter) => {
    onChange({ ...filters, matchRate: filters.matchRate === chip ? null : chip });
  };

  const ChipButton = ({
    active,
    count,
    label,
    onClick,
    colorClass = 'bg-slate-700/80 text-gray-300 border-slate-600',
    activeClass = 'bg-gold/20 text-gold border-gold/50',
  }: {
    active: boolean;
    count: number;
    label: string;
    onClick: () => void;
    colorClass?: string;
    activeClass?: string;
  }) => (
    <button
      type="button"
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }}}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50
        ${active ? activeClass : colorClass} hover:opacity-90`}
    >
      {label}
      <span className={`font-mono-numbers text-[10px] px-1.5 py-0.5 rounded-full
        ${active ? 'bg-gold/20 text-gold' : 'bg-slate-800 text-gray-500'}`}>
        {count}
      </span>
    </button>
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-gray-600 uppercase tracking-wider mr-1">Statut</span>
      <ChipButton
        active={filters.status.has('has_pdf')}
        count={counts.has_pdf}
        label="Avec PDF"
        onClick={() => toggleStatus('has_pdf')}
        colorClass="bg-slate-800 text-gray-400 border-slate-700"
        activeClass="bg-emerald-900/30 text-emerald-400 border-emerald-700/50"
      />
      <ChipButton
        active={filters.status.has('no_pdf')}
        count={counts.no_pdf}
        label="Pas de PDF"
        onClick={() => toggleStatus('no_pdf')}
        colorClass="bg-slate-800 text-gray-500 border-slate-700"
        activeClass="bg-slate-700 text-gray-300 border-slate-500"
      />

      <div className="w-px h-4 bg-slate-700 mx-1" />

      <span className="text-xs text-gray-600 uppercase tracking-wider mr-1">Correspondance</span>
      <ChipButton
        active={filters.matchRate === 'zero'}
        count={counts.zero}
        label="0%"
        onClick={() => setMatchRate('zero')}
        colorClass="bg-slate-800 text-gray-500 border-slate-700"
        activeClass="bg-red-900/30 text-red-400 border-red-700/50"
      />
      <ChipButton
        active={filters.matchRate === 'above_zero'}
        count={counts.above_zero}
        label=">0%"
        onClick={() => setMatchRate('above_zero')}
        colorClass="bg-slate-800 text-gray-500 border-slate-700"
        activeClass="bg-amber-900/30 text-amber-400 border-amber-700/50"
      />
      <ChipButton
        active={filters.matchRate === 'above_fifty'}
        count={counts.above_fifty}
        label=">50%"
        onClick={() => setMatchRate('above_fifty')}
        colorClass="bg-slate-800 text-gray-500 border-slate-700"
        activeClass="bg-emerald-900/30 text-emerald-400 border-emerald-700/50"
      />
      <ChipButton
        active={filters.matchRate === 'hundred'}
        count={counts.hundred}
        label="100%"
        onClick={() => setMatchRate('hundred')}
        colorClass="bg-slate-800 text-gray-500 border-slate-700"
        activeClass="bg-emerald-900/30 text-emerald-400 border-emerald-700/50"
      />

      {hasAnyFilter && (
        <>
          <div className="w-px h-4 bg-slate-700 mx-1" />
          <button
            type="button"
            onClick={onReset}
            className="text-xs text-gray-500 hover:text-gray-300 underline transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 rounded px-1"
          >
            Réinitialiser
          </button>
        </>
      )}
    </div>
  );
}

// ── Summary Strip ─────────────────────────────────────────────────────────────
function SummaryStrip({ banks }: { banks: BankResult[] }) {
  const total = banks.length;
  const fullMatch = banks.filter((b) => b.has_pdf && b.score === 100).length;
  const partialMatch = banks.filter((b) => b.has_pdf && b.score > 50 && b.score < 100).length;
  const lowMatch = banks.filter((b) => b.has_pdf && b.score > 0 && b.score <= 50).length;

  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 py-1">
      <span className="font-mono-numbers">
        <span className="text-gray-300 font-semibold">{total}</span> banques traitées
      </span>
      <span className="text-slate-700">·</span>
      <span className="font-mono-numbers">
        <span className="text-emerald-400 font-semibold">{fullMatch}</span> parfaites (100%)
      </span>
      <span className="text-slate-700">·</span>
      <span className="font-font-mono-numbers">
        <span className="text-emerald-500 font-semibold">{partialMatch}</span> bonnes (&gt;50%)
      </span>
      <span className="text-slate-700">·</span>
      <span className="font-mono-numbers">
        <span className="text-amber-400 font-semibold">{lowMatch}</span> faibles
      </span>
    </div>
  );
}

// ── TransactionTable ───────────────────────────────────────────────────────────
function TransactionTable({
  transactions,
  bankFilter,
  banks,
  compact = false,
  onBankFilterChange,
}: {
  transactions: Transaction[];
  bankFilter: BankResult | null;
  banks: BankResult[];
  compact?: boolean;
  onBankFilterChange: (bank: BankResult | null) => void;
}) {
  const [statutFilter, setStatutFilter] = useState('all');
  const [search, setSearch] = useState('');

  const filtered = useMemo(() =>
    transactions.filter((t) => {
      if (!isSelectedBankRow(t, bankFilter)) return false;
      if (statutFilter !== 'all' && t.Statut !== statutFilter) return false;
      if (search && !t.Indicateur?.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    }),
    [transactions, bankFilter, statutFilter, search]
  );

  return (
    <div className={`flex flex-col h-full animate-fade-up ${compact ? '[&_th]:!p-1 [&_td]:!p-1' : ''}`} style={{ animationDelay: '100ms' }}>
      {/* Filters */}
      <div className={`flex flex-wrap items-center gap-2 shrink-0 ${compact ? 'mb-1' : 'mb-3'}`}>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Rechercher un indicateur…"
          className="flex-1 min-w-40 px-3 py-1.5 rounded-lg bg-background-lighter border border-slate-700 text-sm text-gray-300 placeholder-gray-600 focus:outline-none focus:border-slate-500"
        />
        <select
          value={bankFilter ? bankKey(bankFilter, banks.indexOf(bankFilter)) : 'all'}
          onChange={(e) => onBankFilterChange(
            e.target.value === 'all'
              ? null
              : banks.find((bank, index) => bankKey(bank, index) === e.target.value) ?? null
          )}
          className="px-3 py-1.5 rounded-lg bg-background-lighter border border-slate-700 text-sm text-gray-300 focus:outline-none focus:border-slate-500"
        >
          <option value="all">Toutes les banques</option>
          {banks.map((bank, index) => (
            <option key={bankKey(bank, index)} value={bankKey(bank, index)}>{bank.bank}</option>
          ))}
        </select>
        <select
          value={statutFilter}
          onChange={(e) => setStatutFilter(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-background-lighter border border-slate-700 text-sm text-gray-300 focus:outline-none focus:border-slate-500"
        >
          <option value="all">Tous les statuts</option>
          {Object.keys(STATUT_CONFIG).map((s) => <option key={s} value={s}>{STATUT_CONFIG[s].label}</option>)}
        </select>
        <span className="text-xs text-gray-600 font-mono-numbers ml-auto">{filtered.length} lignes</span>
      </div>

      <div className="bg-background-lighter rounded-lg border border-slate-800 overflow-hidden flex flex-col flex-1 min-h-0">
        <div className="overflow-x-auto overflow-y-auto flex-1 h-full min-h-[300px]">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-background-elevated z-10 shadow-sm">
              <tr className="border-b border-slate-800 text-gray-500 uppercase tracking-wider">
                <th className="text-left p-2.5 font-medium">Entité</th>
                <th className="text-left p-2.5 font-medium">Indicateur</th>
                <th className="text-right p-2.5 font-medium">Résultat</th>
                <th className="text-right p-2.5 font-medium">PDF EBA</th>
                <th className="text-right p-2.5 font-medium">Écart</th>
                <th className="text-center p-2.5 font-medium">Statut</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((tx, i) => {
                const cfg = getStatutConfig(tx.Statut);
                const resultVal = tx['Valeur resultats'] ?? tx.resultValue ?? tx.csvAmount;
                const pdfVal = tx['Valeur PDF (EBA)'] ?? tx.pdfValue ?? tx.pdfAmount;
                const ecart = tx.Ecart ?? tx.difference;
                const bigGap = isSignificantGap(tx);
                return (
                  <tr
                    key={i}
                    className={`border-b border-slate-800/40 last:border-0 transition-colors ${
                      bigGap
                        ? 'bg-red-950/40 hover:bg-red-950/60'
                        : 'hover:bg-background-elevated/60'
                    }`}
                  >
                    <td className={`p-2.5 max-w-[160px] truncate ${bigGap ? 'text-red-300/70' : 'text-gray-400'}`} title={tx.Entité}>{tx.Entité ?? '—'}</td>
                    <td className={`p-2.5 font-medium ${bigGap ? 'text-red-200' : 'text-gray-300'}`}>{tx.Indicateur ?? tx.indicator ?? tx.reference ?? '—'}</td>
                    <td className={`p-2.5 text-right font-mono-numbers ${bigGap ? 'text-red-200' : 'text-gray-300'}`}>{fmtNum(resultVal)}</td>
                    <td className={`p-2.5 text-right font-mono-numbers ${bigGap ? 'text-red-200' : 'text-gray-300'}`}>{fmtNum(pdfVal)}</td>
                    <td className={`p-2.5 text-right font-mono-numbers font-semibold ${bigGap ? 'text-red-400' : ecart && Math.abs(ecart) > 0 ? 'text-amber-400' : 'text-gray-600'}`}>
                      {fmtNum(ecart)}
                    </td>
                    <td className="p-2.5 text-center">
                      <span className={`inline-flex items-center justify-center text-xs px-2 py-0.5 rounded whitespace-nowrap ${cfg.bgColor} ${cfg.color} ${bigGap ? 'font-semibold ring-1 ring-red-500/30' : ''}`}>
                        {cfg.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-gray-600 text-sm">
                    {bankFilter !== null || statutFilter !== 'all' || search
                      ? 'Aucun résultat pour ces filtres.'
                      : 'Aucune donnée disponible.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── AISynthesis — lazy load panel ─────────────────────────────────────────────
function AISynthesisPanel({ resultId, initialText }: { resultId: string; initialText: string }) {
  const [text, setText] = useState(initialText);
  const [loading, setLoading] = useState(false);
  const [generated, setGenerated] = useState(!!initialText);
  const [error, setError] = useState('');

  const generate = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`${API}/api/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result_id: resultId }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.error ?? 'Erreur inconnue');
      }
      const data = await resp.json();
      setText(data.aiSynthesis ?? '');
      setGenerated(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur inconnue');
    } finally {
      setLoading(false);
    }
  }, [resultId]);

  const lines = text?.split('\n').filter(Boolean) ?? [];

  return (
    <div className="bg-background-lighter border border-slate-800 rounded-lg p-5">
      <div className="flex items-center gap-2 mb-4">
        <div className={`w-2 h-2 rounded-full ${loading ? 'bg-amber-400 animate-pulse' : 'bg-gold animate-pulse-subtle'}`} />
        <h3 className="text-sm font-medium text-gray-300">Synthèse IA</h3>
        <span className="text-xs text-gray-600 ml-auto">Ollama · qwen2.5</span>
      </div>

      {!generated && !loading && (
        <div className="flex flex-col items-center gap-3 py-4">
          <p className="text-sm text-gray-500 text-center">
            La synthèse est générée à la demande pour ne pas ralentir le chargement.
          </p>
          <button
            id="generate-ai-summary-btn"
            onClick={generate}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-gold/10 border border-gold/30 text-gold hover:bg-gold/20 hover:border-gold/50 text-sm font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Générer la synthèse
          </button>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-3 py-4">
          <svg className="w-5 h-5 animate-spin text-gold" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm text-gray-400">Génération en cours via Ollama…</span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 py-2 text-sm text-red-400">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {error}
          <button onClick={generate} className="ml-2 underline hover:text-red-300 text-xs">Réessayer</button>
        </div>
      )}

      {generated && !loading && lines.length > 0 && (
        <div className="space-y-2 animate-fade-up">
          {lines.map((line, i) => (
            <p key={i} className="text-sm text-gray-300 leading-relaxed">{line}</p>
          ))}
          <button
            onClick={generate}
            className="mt-2 text-xs text-gray-600 hover:text-gray-400 underline transition-colors"
          >
            Regénérer
          </button>
        </div>
      )}

      {generated && !loading && lines.length === 0 && (
        <p className="text-sm text-gray-600 italic">Aucune synthèse disponible.</p>
      )}
    </div>
  );
}

// ── Empty Filter State ─────────────────────────────────────────────────────────
const EMPTY_FILTERS: ActiveFilters = { status: new Set(), matchRate: null };

// ── ResultsView (main export) ─────────────────────────────────────────────────
export function ResultsView({ result, onDownload, onBack }: ResultsViewProps) {
  const hasBankResults = result.bank_results && result.bank_results.length > 0;
  const [selectedBankKey, setSelectedBankKey] = useState<string | null>(null);
  const [bankFilters, setBankFilters] = useState<ActiveFilters>(EMPTY_FILTERS);

  useEffect(() => {
    setSelectedBankKey(null);
    setBankFilters(EMPTY_FILTERS);
  }, [result.id]);

  const filteredBanks = useMemo(() => {
    if (!result.bank_results) return [];
    return result.bank_results.filter((b) => matchesBankFilters(b, bankFilters));
  }, [result.bank_results, bankFilters]);

  const selectedBank = useMemo(
    () => result.bank_results?.find((bank, index) => bankKey(bank, index) === selectedBankKey) ?? null,
    [result.bank_results, selectedBankKey]
  );

  const handleSelectBankKey = (key: string | null) => {
    setSelectedBankKey(key);
  };

  const handleSelectBank = (bank: BankResult | null) => {
    setSelectedBankKey(
      bank ? bankKey(bank, result.bank_results?.indexOf(bank) ?? -1) : null
    );
  };

  const handleResetFilters = () => {
    setBankFilters(EMPTY_FILTERS);
  };

  // Prevent background scrolling when modal is open
  useEffect(() => {
    if (selectedBankKey) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'auto';
    }
    return () => { document.body.style.overflow = 'auto'; };
  }, [selectedBankKey]);

  return (
    <div className="h-screen overflow-y-auto p-6 relative">
      {/* Background content wrapped for potential blur effect if modal is open */}
      <div className={`max-w-7xl mx-auto space-y-6 transition-all duration-300 ${selectedBankKey ? 'opacity-40 blur-[2px] pointer-events-none scale-[0.99]' : ''}`}>

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={onBack}
              className="p-2 rounded-lg bg-background-lighter border border-slate-700 hover:border-slate-600 text-gray-400 hover:text-gray-200 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50"
              aria-label="Retour"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
            </button>
            <div>
              <h2 className="text-base font-semibold text-gray-200">Résultats du rapprochement</h2>
              <div className="text-xs text-gray-500 flex items-center gap-2 mt-0.5">
                {result.report_date && <span className="font-mono-numbers text-gold/80">{result.report_date}</span>}
                <span>{result.csvFile.name}</span>
                {result.processingTime && <span className="text-gray-700">· {result.processingTime}s</span>}
              </div>
            </div>
          </div>
          <button
            id="download-excel-btn"
            onClick={onDownload}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-background-lighter border border-slate-700 hover:border-gold/40 text-sm text-gray-300 hover:text-gray-100 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Télécharger Excel
          </button>
        </div>

        {/* Score + summary */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <div className="bg-background-lighter rounded-xl border border-slate-800 p-6 flex flex-col justify-between animate-fade-up">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-3">Score de conformité</div>
            <AnimatedScore score={result.complianceScore} />
            <div className="text-xs text-gray-600 mt-2">{result.summary.total} indicateurs analysés</div>
          </div>

          {[
            { label: 'Correspondances', value: result.summary.matched, color: 'text-emerald-400' },
            { label: 'Écarts significatifs', value: result.summary.ecart, color: 'text-red-400' },
            { label: 'PDF non disponibles', value: result.summary.pdfOnly, color: 'text-gray-500' },
          ].map((stat) => (
            <div key={stat.label} className="bg-background-lighter rounded-xl border border-slate-800 p-5 animate-fade-up">
              <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{stat.label}</div>
              <div className={`font-mono-numbers text-3xl font-bold ${stat.color}`}>{stat.value}</div>
            </div>
          ))}
        </div>

        {/* Per-bank grid with filter bar + summary strip */}
        {hasBankResults && (
          <div className="animate-fade-up space-y-3" style={{ animationDelay: '100ms' }}>
            <div className="flex items-center justify-between">
              <h3 className="text-xs text-gray-500 uppercase tracking-wider">Score par banque</h3>
            </div>

            {/* Summary strip */}
            <SummaryStrip banks={result.bank_results!} />

            {/* Filter chips */}
            <ResultsFilterBar
              banks={result.bank_results!}
              filters={bankFilters}
              onChange={setBankFilters}
              onReset={handleResetFilters}
            />

            {/* Bank grid */}
            <BankScoreGrid
              banks={filteredBanks}
              selectedBankKey={selectedBankKey}
              onSelectBank={handleSelectBankKey}
            />
          </div>
        )}

        {/* AI Summary — lazy / on demand */}
        <AISynthesisPanel resultId={result.id} initialText={result.aiSynthesis ?? ''} />

        {/* Global Detailed table */}
        <div className="mt-8 pt-6 border-t border-slate-800/60">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs text-gray-500 uppercase tracking-wider">Détail de tous les indicateurs</h3>
            <span className="text-xs text-gray-700 flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-sm bg-red-950/70 border border-red-800/50" />
              Fond rouge = écart significatif
            </span>
          </div>
          <TransactionTable
            transactions={result.transactions}
            bankFilter={null}
            banks={result.bank_results ?? []}
            onBankFilterChange={handleSelectBank}
          />
        </div>

        <div className="h-6" />
      </div>

      {/* =========================================================================
          Detail Modal Overlay
          ========================================================================= */}
      {selectedBank && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm animate-fade-in"
          onClick={() => setSelectedBankKey(null)}
        >
          <div
            className="relative w-full max-w-6xl h-[calc(100vh-1.5rem)] flex flex-col bg-background-light rounded-2xl border border-slate-700 shadow-2xl overflow-hidden animate-fade-up"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-background-lighter shrink-0">
               <div>
                 <h3 className="text-xl font-semibold text-gray-100">{selectedBank.bank}</h3>
                 <div className="text-sm text-gray-500 mt-1 flex items-center gap-3">
                   <span className={`font-mono-numbers font-medium ${getScoreColors(selectedBank.score, selectedBank.has_pdf).text}`}>
                     Score: {selectedBank.has_pdf ? `${selectedBank.score}%` : 'Pas de PDF'}
                   </span>
                   <span>·</span>
                   <span className="font-mono-numbers">{selectedBank.matched}/{selectedBank.total} validés</span>
                   <span>·</span>
                   <span className="font-mono-numbers">
                     PDF: {selectedBank.pdf_metrics_found ?? 0}/{selectedBank.expected_metrics ?? selectedBank.total} trouvés
                   </span>
                   {selectedBank.reports_with_parent && (
                     <span className="text-indigo-300">
                       · Consolidé avec {selectedBank.parent_group}
                     </span>
                   )}
                   {/* Red gap legend in modal */}
                   <span className="ml-2 flex items-center gap-1 text-xs text-gray-600">
                     <span className="inline-block w-2 h-2 rounded-sm bg-red-950/70 border border-red-800/50" />
                     rouge = écart
                   </span>
                 </div>
               </div>
               <button
                  onClick={() => setSelectedBankKey(null)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-slate-500 text-gray-300 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-gold/50 whitespace-nowrap"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                  </svg>
                  Retour aux banques
                </button>
            </div>

            <TransactionTable
              transactions={result.transactions}
              bankFilter={selectedBank}
              banks={result.bank_results ?? []}
              compact
              onBankFilterChange={handleSelectBank}
            />
          </div>
        </div>
      )}
    </div>
  );
}
