// PostCSS pipeline for non-Tailwind CSS files (e.g. component CSS Modules and
// raw .css imports in src/components/**). Tailwind v4 has its own CSS pipeline
// (Lightning CSS via @tailwindcss/vite) and won't be double-processed.
//
// `autoprefixer` reads `browserslist` from package.json and emits the right
// vendor prefixes — `-webkit-backdrop-filter` for Safari <17.4,
// `-webkit-mask` for Safari <17, etc. Future CSS won't need manual prefixes.
export default {
  plugins: {
    autoprefixer: {},
  },
}
