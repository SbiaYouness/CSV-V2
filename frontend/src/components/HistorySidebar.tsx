import { ReconciliationResult } from '../types';
import { formatDistanceToNow } from '../utils/dateUtils';
import { ScoreBadge } from './ScoreBadge';

interface HistorySidebarProps {
  history: ReconciliationResult[];
  selectedId: string | null;
  onSelect: (result: ReconciliationResult) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

export function HistorySidebar({
  history,
  selectedId,
  onSelect,
  isCollapsed,
  onToggleCollapse,
}: HistorySidebarProps) {
  return (
    <aside
      className={`
        h-screen bg-background-light border-r border-slate-800
        transition-all duration-300 ease-out flex flex-col
        ${isCollapsed ? 'w-16' : 'w-80'}
      `}
    >
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        {!isCollapsed && (
          <span className="text-sm font-medium text-gray-400">Historique</span>
        )}
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded hover:bg-background-lighter text-gray-500 hover:text-gray-300 transition-colors"
          aria-label={isCollapsed ? 'Etendre le panneau' : 'Reduire le panneau'}
        >
          <svg
            className={`w-4 h-4 transition-transform duration-200 ${isCollapsed ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {history.length === 0 && !isCollapsed && (
          <div className="p-4 text-center text-gray-500 text-sm">
            Aucune analyse precedente
          </div>
        )}

        {history.map((item) => (
          <button
            key={item.id}
            onClick={() => onSelect(item)}
            className={`
              w-full text-left p-3 border-b border-slate-800/50
              transition-all duration-150
              ${isCollapsed ? 'flex justify-center' : 'flex flex-col gap-2'}
              ${selectedId === item.id
                ? 'bg-background-lighter border-l-2 border-l-gold'
                : 'hover:bg-background-lighter border-l-2 border-l-transparent'}
            `}
          >
            {isCollapsed ? (
              <div className="text-xs font-mono-numbers text-gold">
                {item.complianceScore}%
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-2">
                  <span className="text-xs text-gray-500">
                    {formatDistanceToNow(new Date(item.date))}
                  </span>
                  <ScoreBadge score={item.complianceScore} />
                </div>
                <div className="space-y-1">
                  <div className="text-sm text-gray-300 truncate font-mono-numbers">
                    {item.pdfFile.name}
                  </div>
                  <div className="text-xs text-gray-500 truncate font-mono-numbers">
                    {item.csvFile.name}
                  </div>
                </div>
              </>
            )}
          </button>
        ))}
      </div>
    </aside>
  );
}
