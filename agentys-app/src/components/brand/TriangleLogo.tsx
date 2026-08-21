interface TriangleLogoProps {
  size?: number
  className?: string
}

/**
 * Agentys brand triangle — the canonical logo mark used across LoginPage,
 * loading states, status cards and the onboarding tour. Keep this file as
 * the single source of truth so visual tweaks propagate everywhere.
 */
export function TriangleLogo({ size = 48, className }: TriangleLogoProps) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M16 2.5L1.5 29.5h29z"
        stroke="#2dd4bf"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        fill="none"
        opacity="0.7"
      />
      <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488" />
      <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-primary, #f0f1f5)" />
    </svg>
  )
}
