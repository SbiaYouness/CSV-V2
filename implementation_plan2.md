# Concilio Frontend Redesign — Diagnostic & Implementation Plan

## 1. Diagnostic Report

### 1.1 Component Map

| Component | File | Purpose |
|---|---|---|
| App | [App.tsx](file:///e:/00%20AI%20WORK/frontend/src/App.tsx) | Root. Manages `appState` (`upload` → `processing` → `results`), history, and orchestrates views |
| UploadWorkspace | [UploadWorkspace.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/UploadWorkspace.tsx) | Initial upload/selection screen. Fetches `/api/files`, lets user pick an Excel + ZIP bank PDFs |
| ProcessingView | [ProcessingView.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ProcessingView.tsx) | Animated processing progress stepper |
| ResultsView | [ResultsView.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ResultsView.tsx) | Post-run dashboard: score cards, per-bank grid (`BankScoreGrid`), detail table (`TransactionTable`), AI synthesis |
| HistorySidebar | [HistorySidebar.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/HistorySidebar.tsx) | Left sidebar showing previous analysis results |
| ScoreBadge | [ScoreBadge.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ScoreBadge.tsx) | Small badge component for compliance score |

### 1.2 State Management

**Local state throughout** — no Redux, Zustand, or Context. Each component manages its own state:

- **App.tsx**: `appState` (discriminated union: `upload | processing | results`), `history[]`, `selectedHistoryId`
- **UploadWorkspace**: `files` (from API), `selectedExcel`, `checkedZips` (Set), `activeDate` (date tab filter)
- **ResultsView**: `selectedBank` (string, `'all'` or bank name) — shared between `BankScoreGrid` and `TransactionTable` via prop drilling
- **TransactionTable**: its own `statutFilter`, `search` — internally managed, not synced with parent

### 1.3 Current Selection Default — The Core Problem

In [UploadWorkspace.tsx:35](file:///e:/00%20AI%20WORK/frontend/src/components/UploadWorkspace.tsx#L35):

```typescript
// Default: check all zips
setCheckedZips(new Set(data.zip_files.map((z) => z.name)));
```

**All ZIP files are selected by default on load.** The first Excel file is also auto-selected. The date tab defaults to the most recent date, but `checkedZips` contains *all* zips from *all* dates — not just the active date tab. This means the user sees a filtered view (one date) but has invisible selections from other dates still active.

### 1.4 Current Click-Path: "Land on Page" → "See One Bank's Data"

> [!CAUTION]
> This takes **7+ deliberate actions**, not counting scrolling:

1. **Land on page** → everything is pre-selected (all ZIPs checked, first Excel auto-picked)
2. **Click "Tout désélectionner"** to clear all (if you don't want all banks)
3. **Click a date tab** (e.g., `2025-12-31`) to narrow to one reporting period
4. **Scroll through the list** to find the banks you want
5. **Click checkboxes** on specific banks one by one (no search, no type-to-filter)
6. **Click "Lancer le rapprochement"** to run the comparison
7. **Wait for processing** → land on results dashboard
8. **Find the bank card in the grid** → click **"Voir données"** button on that bank

**And step 8 is broken** — the "Voir données" button doesn't reliably show that bank's data (diagnosed below).

### 1.5 "Voir données" Bug — Root Cause

In [BankScoreGrid](file:///e:/00%20AI%20WORK/frontend/src/components/ResultsView.tsx#L54-L92), the click handler is:

```tsx
onClick={() => onSelectBank(selected ? 'all' : b.bank)}
```

This sets `selectedBank` in `ResultsView` state. Then `TransactionTable` receives this as `bankFilter` prop and filters by `t.Entité !== bankFilter`.

**The actual bug**: The `bankFilter` value (`b.bank`) comes from `BankResult.bank`, which is the *output_name* (derived via `_output_name_for_col(col)` in the backend). But the transactions use `t.Entité`, which is set to the same `output_name`. So the filter key **should** match.

However, examining more carefully: `BankScoreGrid` uses `b.lei || b.bank` as the React key, but the `selected` check is `selectedBank === b.bank`. The `onSelectBank` call passes `b.bank` correctly. The `TransactionTable` filters `t.Entité !== bankFilter`.

**The likely root cause is a naming mismatch or whitespace issue** — the backend `_output_name_for_col()` may produce slightly different strings from what appears in `Entité`. But there's also a second issue: the `TransactionTable` has its **own** `bankFilter` dropdown which resets independently. When `bankFilter` is passed down from `ResultsView`, the dropdown tries to sync, but there could be a case sensitivity or trimming mismatch between the bank names in `bank_results[].bank` and the distinct `Entité` values extracted from `transactions[]`.

I'll trace and fix this definitively during implementation by adding console logging and testing with real data.

### 1.6 Results Dashboard — No Post-Run Filtering

Currently, the results page has:
- A bank filter dropdown (in `TransactionTable`) — filters the detail table only
- A status dropdown (in `TransactionTable`) — filters the detail table only
- No filter chips, no summary strip, no way to filter the **bank card grid** itself

There is no high-level "No PDF / No data / 0% match / >50% match" filtering over the `BankScoreGrid`. You see all banks at once with no way to narrow.

---

## 2. Proposed Changes

### Phase 1: Create Feature Branch

Create a `frontend-redesign` branch from `main`.

---

### Phase 2: UploadWorkspace Redesign

#### [MODIFY] [UploadWorkspace.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/UploadWorkspace.tsx)

**Goal**: Selection flow should be: **search/scan → select → run** (2-3 actions max).

Changes:
1. **Default state: nothing selected.** Remove the `setCheckedZips(new Set(data.zip_files.map(...)))` line. Start with empty set.
2. **Add a search/filter-as-you-type box** directly above the ZIP list. Typing "BNP" filters the visible list live — no extra click to open a filter panel.
3. **Merge filtering and selection into one interaction.** Remove the separate date-tab filter bar. Instead, integrate date as a secondary filter within the search bar area (e.g., a small dropdown beside the search input, or auto-detected from search terms). The date tabs currently filter *visibility* but don't affect *selection* — this is confusing. New approach: one unified list, searchable, with the date shown per-entry.
4. **Bulk actions always visible**: "Select all (visible)" / "Clear selection" buttons + live counter ("4 of 29 banks selected") permanently visible in the panel header.
5. **Disabled run button with reason**: When `checkedZips.size === 0`, the button reads "Sélectionnez au moins une banque" and is disabled. When `selectedExcel` is empty, it reads "Sélectionnez un classeur Excel". Only when both are satisfied does it become "Lancer le rapprochement" and activate.

> [!IMPORTANT]
> **Keeping the date tabs vs. removing them**: The date tabs serve a real purpose (zip files are organized by reporting period). Rather than removing them entirely, I propose keeping them as **optional quick-filter chips** below the search bar — clicking one filters the list to that date, but doesn't affect which items are selected. This preserves the existing data model while making the flow simpler. The key change is that they no longer auto-select anything.

New layout structure:
```
┌─────────────────────────────────────────────────────────┐
│ Rapprochement Pilier 3 EBA                              │
│ Sélectionnez les rapports et le classeur, puis lancez.  │
├─────────────────────────────────┬───────────────────────┤
│ Rapports PDF (ZIP)              │ Classeur de résultats │
│ [🔍 Rechercher une banque...  ] │                       │
│ [2025-12-31] [2024-12-31] [All] │ ○ file1.xlsx          │
│ ☐ Select all (12) │ Clear      │ ● file2.xlsx          │
│ ─────────────────────────────── │                       │
│ ☐ BNP_2025-12-31.zip           │                       │
│ ☐ SG_2025-12-31.zip            │                       │
│ ☐ CA_2025-12-31.zip            │                       │
│ ...                             │                       │
├─────────────────────────────────┴───────────────────────┤
│ 0 banques sélectionnées        [Sélectionnez au moins  │
│                                  une banque] (disabled) │
└─────────────────────────────────────────────────────────┘
```

---

### Phase 3: Results Dashboard — Filter Bar & Summary Strip

#### [MODIFY] [ResultsView.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ResultsView.tsx)

**3a. Summary Strip** — above the bank grid, add a compact summary:
```
23 banques traitées · 14 correspondances complètes · 5 partielles · 4 sans données
```
Computed client-side from `bank_results`.

**3b. Filter Chips** — below the summary strip, above the `BankScoreGrid`:

| Chip | Logic | Group |
|---|---|---|
| No PDF (6) | `!b.has_pdf` | Status (OR) |
| No data (3) | `b.has_pdf && b.total === 0` | Status (OR) |
| 0% match (2) | `b.has_pdf && b.total > 0 && b.score === 0` | Match rate (exclusive) |
| >0% match (8) | `b.has_pdf && b.total > 0 && b.score > 0` | Match rate (exclusive) |
| >50% match (5) | `b.has_pdf && b.total > 0 && b.score > 50` | Match rate (exclusive) |

- Status chips: OR'd (can select both "No PDF" and "No data")
- Match rate chips: mutually exclusive within group
- Cross-group: AND (e.g., "No PDF" + ">50% match" = banks matching either condition... wait, that's contradictory. Per the spec, status and match rate groups combine with AND. "No PDF" AND ">50% match" would yield 0 results, which is correct behavior.)
- Each chip shows a live count in parentheses
- "Reset filters" link visible when any filter is active
- Empty state: "Aucune banque ne correspond à ces filtres" when filter yields 0

**3c. Backend status mapping for "No data"**: Looking at the backend, `bank_results[]` includes `has_pdf`, `total` (count of compared rows), and `pdf_metrics_found`. A bank where `has_pdf === true` but `total === 0` would mean the PDF existed but produced no comparable rows — this maps to "no data". The `skipped_banks` array (reason: `no_input_data`) covers banks skipped because the Excel column was empty. These are distinct from "no PDF" (where `has_pdf === false`). The backend already exposes enough to distinguish all cases.

> [!NOTE]
> No backend changes needed. The existing `bank_results[].has_pdf`, `.total`, and `.score` fields are sufficient to compute all filter categories.

---

### Phase 4: Fix "Voir données" Bug + Audit All Controls

#### [MODIFY] [ResultsView.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ResultsView.tsx)

1. **Root-cause the bank filter mismatch**: Add defensive trimming on both sides — `b.bank.trim()` in the grid and `t.Entité?.trim()` in the filter. Ensure exact string match.
2. **Verify the `selectedBank` state propagation**: Currently `ResultsView` holds `selectedBank` and passes it to both `BankScoreGrid` (as `selectedBank`) and `TransactionTable` (as `bankFilter`). The `TransactionTable` also has a `<select>` dropdown that calls `onBankFilterChange` (which is `setSelectedBank`). This should work correctly — but I'll verify there's no race condition or stale value.
3. **Test with 3 different banks in sequence** after fix.
4. **Audit all other controls**:
   - Download button (`onDownload`) — trace through `handleDownload` in App.tsx — appears functional
   - Back button — appears functional
   - Status dropdown in TransactionTable — appears functional but will verify
   - Search input in TransactionTable — appears functional but will verify

---

### Phase 5: General UX Polish

#### [MODIFY] [ResultsView.tsx](file:///e:/00%20AI%20WORK/frontend/src/components/ResultsView.tsx)

1. **Color-code match rates consistently**: Use same scale everywhere:
   - 0% = `text-red-400` / `bg-red-900/20`
   - 1–50% = `text-amber-400` / `bg-amber-900/20`
   - \>50% = `text-emerald-400` / `bg-emerald-900/20`
   - No PDF = `text-gray-500` / `bg-slate-800/60`

2. **Keyboard accessibility**: Add `tabIndex`, `onKeyDown` (Enter/Space) handlers to filter chips and bank selection checkboxes. Visible focus rings using `focus-visible:ring-2 focus-visible:ring-gold/50`.

3. **Empty/error states**: Ensure no blank screens:
   - Bank card with no PDF: shows "Pas de PDF" (already done)
   - Bank card with no data: shows "Aucune donnée" (new)
   - Filter results empty: shows message (new, from Phase 3)

4. **Loading state improvements**: The `ProcessingView` already exists and is adequate. No changes needed there.

5. **Responsive layout**: Verify layout at 1366px width. The two-column grid in UploadWorkspace uses `flex` with `flex-1` + `w-80`, which should work. The results grid uses `grid-cols-2 md:grid-cols-3 lg:grid-cols-4`, which is responsive. Will verify and adjust breakpoints if needed.

#### [MODIFY] [index.css](file:///e:/00%20AI%20WORK/frontend/src/index.css)

Add focus-visible utility styles and any new animation keyframes needed for filter chip transitions.

#### [MODIFY] [tailwind.config.js](file:///e:/00%20AI%20WORK/frontend/tailwind.config.js)

Add any new animation/keyframe definitions if needed for chip press/toggle effects.

---

## 3. Files NOT Modified

- **Backend**: No changes to [app.py](file:///e:/00%20AI%20WORK/backend/app.py) or any backend service
- **Types**: [types.ts](file:///e:/00%20AI%20WORK/frontend/src/types.ts) — no changes needed (existing types cover all data)
- **App.tsx**: Minimal or no changes — the `handleAnalyze` signature and `appState` flow don't need to change
- **HistorySidebar**: No changes
- **ScoreBadge**: No changes
- **ProcessingView**: No changes
- **mockData.ts**: No changes

---

## 4. Verification Plan

### Automated
```bash
cd frontend && npm run typecheck
cd frontend && npm run build
```

### Manual Verification (via browser preview)
1. Fresh page load → verify **nothing is selected** by default
2. Type "BNP" in search → verify list filters live → select one bank → verify count shows "1 of N"
3. Click "Lancer le rapprochement" → verify it was disabled before selection, enabled after
4. On results page → verify summary strip shows correct counts
5. Toggle filter chips → verify bank grid updates, counts update, empty state appears when no matches
6. Click "Voir données" on 3 different banks in sequence → verify detail table updates correctly each time
7. Combine two filters (e.g., "No PDF" + ">0% match") → verify AND logic
8. Click "Reset filters" → verify all filters clear
9. Test keyboard navigation: Tab to filter chips, Enter/Space to toggle
10. Verify at 1366px viewport width
