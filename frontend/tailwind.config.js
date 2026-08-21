/**
 * Eepy Host — "Retro Cozy" design system.
 *
 * 16-bit pixel-art warmth: a deep aubergine-brown "night" base with soft
 * blush/pink accents, earthy sage & amber, and warm cream ink. No neon, no
 * glassmorphism — chunky 2px borders, hard (non-blurred) shadows, stepped
 * animations, and dithered textures instead of glows.
 *
 * Fonts (loaded in app/layout.tsx via next/font):
 *   pixel   -> Pixelify Sans (rounded pixel; headings, buttons, nav)
 *   console -> VT323 (retro terminal; logs, code, URLs)
 *   body    -> Nunito (rounded clean sans; prose)
 */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./context/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        night: {
          DEFAULT: "#251C21",
          deep: "#1B1318",
          surface: "#2F2329",
          raise: "#3A2B33",
          border: "#523E49",
          line: "#40303A",
        },
        eepy: {
          blush: "#F2A3B0",
          pink: "#FF7FA6",
          cream: "#F6E7D3",
          sage: "#A3C09A",
          amber: "#EFBD7F",
          lilac: "#B79FD8",
          ember: "#E2726E",
          glow: "rgba(242, 163, 176, 0.35)",
        },
        ink: {
          DEFAULT: "#F6E7D3",
          soft: "#CDBAC4",
          faint: "#9C8894",
          dim: "#77656F",
        },
      },
      fontFamily: {
        pixel: ['var(--font-pixel)', '"Trebuchet MS"', 'sans-serif'],
        console: ['var(--font-console)', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
        body: ['var(--font-body)', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        pixel: '0 4px 0 0 rgba(16, 9, 13, 0.5)',
        'pixel-sm': '0 2px 0 0 rgba(16, 9, 13, 0.5)',
        'pixel-lg': '0 6px 0 0 rgba(16, 9, 13, 0.55)',
        'pixel-inset': 'inset 0 2px 0 0 rgba(255,255,255,0.05), inset 0 -3px 0 0 rgba(0,0,0,0.28)',
        'glow-blush': '0 0 0 2px rgba(242,163,176,0.18), 0 0 28px rgba(255,127,166,0.2)',
        'glow-sage': '0 0 0 2px rgba(163,192,154,0.18), 0 0 24px rgba(163,192,154,0.16)',
      },
      keyframes: {
        twinkle: {
          '0%, 100%': { opacity: '0.2' },
          '50%': { opacity: '1' },
        },
        'float-z': {
          '0%': { transform: 'translateY(0)', opacity: '0' },
          '25%': { opacity: '1' },
          '100%': { transform: 'translateY(-16px)', opacity: '0' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        led: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
      animation: {
        twinkle: 'twinkle 2.6s steps(2, jump-none) infinite',
        'float-z': 'float-z 2.8s steps(7) infinite',
        blink: 'blink 1.1s steps(1) infinite',
        led: 'led 1.6s steps(2) infinite',
      },
    },
  },
  plugins: [],
};
