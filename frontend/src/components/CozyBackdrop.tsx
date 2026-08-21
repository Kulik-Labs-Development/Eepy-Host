// CozyBackdrop — the shared night-sky layer behind every page:
// banded retro sky + dither texture + a field of twinkling pixel stars.
// Fixed position, purely decorative, never intercepts pointer events.

// Deterministic PRNG (mulberry32) so SSR and client render identical stars.
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Star {
  x: number;
  y: number;
  s: number;
  delay: number;
  color: string;
}

function makeStars(count: number, seed: number): Star[] {
  const rand = mulberry32(seed);
  return Array.from({ length: count }, (_, i) => {
    const r = rand();
    return {
      x: rand() * 100,
      y: rand() * 78, // keep stars in the upper "sky" region
      s: rand() > 0.85 ? 4 : rand() > 0.4 ? 3 : 2,
      delay: rand() * 4,
      color:
        i % 11 === 0
          ? 'bg-eepy-pink/80'
          : i % 7 === 0
            ? 'bg-eepy-lilac/60'
            : r > 0.7
              ? 'bg-eepy-cream/60'
              : 'bg-eepy-cream/35',
    };
  });
}

const STARS = makeStars(56, 20260821);

export default function CozyBackdrop({ starCount }: { starCount?: number }) {
  const stars = starCount && starCount !== 56 ? makeStars(starCount, starCount) : STARS;
  return (
    <div aria-hidden className="fixed inset-0 -z-10 overflow-hidden pointer-events-none">
      <div className="absolute inset-0 tex-bands" />
      <div className="absolute inset-0 tex-dither" />
      {stars.map((st, i) => (
        <span
          key={i}
          className={`absolute animate-twinkle ${st.color}`}
          style={{
            left: `${st.x}%`,
            top: `${st.y}%`,
            width: st.s,
            height: st.s,
            animationDelay: `-${st.delay}s`,
          }}
        />
      ))}
    </div>
  );
}
