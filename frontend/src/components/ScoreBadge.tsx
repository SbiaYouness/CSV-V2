interface ScoreBadgeProps {
  score: number;
  size?: 'sm' | 'md';
}

export function ScoreBadge({ score, size = 'sm' }: ScoreBadgeProps) {
  const getScoreColor = () => {
    if (score >= 90) return 'bg-emerald-900/50 text-emerald-400 border-emerald-800';
    if (score >= 70) return 'bg-gold/10 text-gold border-gold/30';
    return 'bg-red-900/50 text-red-400 border-red-800';
  };

  return (
    <span
      className={`
        inline-flex items-center justify-center rounded border font-mono-numbers font-medium
        ${getScoreColor()}
        ${size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'}
      `}
    >
      {score}%
    </span>
  );
}
