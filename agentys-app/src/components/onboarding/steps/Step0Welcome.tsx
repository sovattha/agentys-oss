import { useTranslation } from 'react-i18next'

interface Step0WelcomeProps {
  onNext: () => void
  onSkip: () => void
}

const TriangleLogo = () => (
  <div className="w0-logo-orbit" aria-hidden="true">
    <svg aria-hidden="true" className="w0-logo-svg" width={80} height={80} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M16 2.5L1.5 29.5h29z" stroke="#2dd4bf" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" fill="none"/>
      <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
      <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-base, #faf9f7)" opacity="0.92"/>
    </svg>
  </div>
)

/**
 * Split un texte en mots (préserve la ponctuation collée) et les wrappe dans
 * des <span> avec un animation-delay croissant pour un reveal word-by-word.
 * Base delay + offset par mot — chaque mot apparaît 70ms après le précédent.
 */
function RevealedWords({
  text,
  className,
  baseDelayMs = 0,
}: {
  text: string
  className: string
  baseDelayMs?: number
}) {
  // Split en préservant les espaces (pour conserver le layout naturel wrap)
  const tokens = text.split(/(\s+)/)
  let wordIndex = 0
  return (
    <span className={className}>
      {tokens.map((token, i) => {
        if (/^\s+$/.test(token)) {
          return <span key={i} aria-hidden="true">{token}</span>
        }
        const delay = baseDelayMs + wordIndex * 70
        wordIndex += 1
        return (
          <span
            key={i}
            className="w0-headline-word"
            style={{ animationDelay: `${delay}ms` }}
          >
            {token}
          </span>
        )
      })}
    </span>
  )
}

export function Step0Welcome({ onNext, onSkip: _onSkip }: Step0WelcomeProps) {
  const { t } = useTranslation('onboarding')
  const lines = t('step0_headline').split('\n')
  // Calcule la durée totale de la cascade de mots pour démarrer le promise+CTA
  // juste après le dernier mot.
  const totalWords =
    lines[0].split(/\s+/).filter(Boolean).length +
    (lines[1]?.split(/\s+/).filter(Boolean).length || 0)
  const headlineDoneAt = 250 + totalWords * 70 + 300 // base + cascade + settle

  return (
    <div className="w0-root">
      {/* Atmospheric radial glow */}
      <div className="w0-glow" aria-hidden="true" />
      <div className="w0-glow w0-glow-2" aria-hidden="true" />

      <div className="w0-content">
        {/* Logo with orbit rings */}
        <div className="w0-logo-wrap w0-reveal w0-reveal-1">
          <TriangleLogo />
        </div>

        {/* Headline — mots révélés séquentiellement, accent sur la 2e ligne */}
        <h1 className="w0-headline w0-headline-worded">
          <RevealedWords text={lines[0]} className="w0-headline-main" baseDelayMs={250} />
          {lines[1] && (
            <>
              <br />
              <RevealedWords
                text={lines[1]}
                className="w0-headline-accent"
                baseDelayMs={250 + lines[0].split(/\s+/).filter(Boolean).length * 70 + 100}
              />
            </>
          )}
        </h1>

        {/* Supporting text — apparaît après la cascade headline */}
        <p
          className="w0-promise w0-reveal-after"
          style={{ animationDelay: `${headlineDoneAt}ms` }}
        >
          {t('step0_promise')}
        </p>

        {/* CTA — arrow only, reveal final */}
        <button
          className="w0-btn w0-reveal-after"
          style={{ animationDelay: `${headlineDoneAt + 180}ms` }}
          onClick={onNext}
          aria-label={t('step0_aria_cta')}
        >
          <svg className="w0-btn-arrow" width="22" height="22" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>
    </div>
  )
}
