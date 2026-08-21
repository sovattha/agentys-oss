import './ScoreRing.css';

interface ScoreRingProps {
  score: number;
  size?: number;
  stroke?: number;
  animate?: boolean;
  label?: string;
}

function colorForScore(score: number): string {
  if (score >= 75) return 'var(--success, #16a34a)';
  if (score >= 50) return 'var(--color-amber, #f59e0b)';
  return 'var(--error, #dc2626)';
}

export function ScoreRing({ score, size = 44, stroke = 4, animate = true, label }: ScoreRingProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;
  const color = colorForScore(clamped);

  return (
    <div
      className={`score-ring${animate ? ' score-ring--animate' : ''}`}
      style={{ width: size, height: size, ['--ring-color' as string]: color }}
      role="img"
      aria-label={label ? `${label}: ${clamped}/100` : `Score ${clamped}/100`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border-subtle, rgba(0,0,0,0.08))"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: animate ? 'stroke-dashoffset 900ms cubic-bezier(0.22, 1, 0.36, 1)' : undefined }}
        />
      </svg>
      <span className="score-ring-value" style={{ color }}>{clamped}</span>
    </div>
  );
}
