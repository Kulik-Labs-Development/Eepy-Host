module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        void: {
          DEFAULT: "#0B0B0C",
          surface: "#161618",
          border: "#2A2A2C"
        },
        eepy: {
          lavender: "#C3B1E1",
          mint: "#B2E2D2",
          peach: "#FADADD",
          glow: "rgba(195, 177, 225, 0.4)"
        }
      },
      borderRadius: {
        'eepy': '1.5rem',
      }
    },
  },
  plugins: [],
}
