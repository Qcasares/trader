/**
 * Tailwind v4 is a PostCSS plugin and needs no config file of its own — the
 * design tokens live in `src/app/globals.css` under `@theme`, beside the prose
 * that explains why each value is what it is. Keeping them there rather than in
 * a JavaScript config is the point: the palette was solved for contrast, and
 * the reasoning belongs next to the numbers.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
