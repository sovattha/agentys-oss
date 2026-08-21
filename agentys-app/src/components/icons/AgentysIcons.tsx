/* ============================================================================
 * Premium hand-crafted icons for the "Personnalisation" settings section.
 *
 * Design principles:
 *   • 24×24 viewBox · stroke 1.75 · round caps/joins — confident weight.
 *   • Simple, iconic silhouettes — readable at 22–26px without squinting.
 *   • One filled "accent dot" per icon = focal point (avoids pure-outline
 *     flatness without going duotone-busy).
 *   • Shared inner bounding box ≈ 16×16 so all 4 tiles read equal weight.
 * ============================================================================ */

interface IconProps {
  size?: number
  strokeWidth?: number
}

/** Brain — lucide's hand-tuned brain silhouette with an added AI spark. */
export function BrainIcon({ size = 24, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
    >
      {/* Left lobe */}
      <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 0 0 12 18Z" />
      {/* Right lobe */}
      <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
      {/* Inner fold — gives the brain a gyrus */}
      <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
      {/* Neural spark — the AI accent */}
      <circle cx="12" cy="15" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  )
}

/** Diploma — rolled certificate with a wax seal + ribbon tails. */
export function DiplomaIcon({ size = 24, strokeWidth = 1.75 }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round"
    >
      {/* Parchment roll — scroll with curled ends */}
      <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3" />
      <path d="M6 4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9" />
      {/* Header divider */}
      <path d="M7 8h10" />
      {/* Text line */}
      <path d="M7 11h6" />
      {/* Medal seal (overlaps bottom of scroll) */}
      <circle cx="15" cy="17" r="3" />
      {/* Ribbon tails from the seal */}
      <path d="m13 19-1 4 3-1.5 3 1.5-1-4" />
      {/* Star on seal — prestige accent */}
      <circle cx="15" cy="17" r="0.85" fill="currentColor" stroke="none" />
    </svg>
  )
}

