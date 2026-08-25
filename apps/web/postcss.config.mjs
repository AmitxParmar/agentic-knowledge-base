/**
 * postcss.config.mjs
 * ------------------
 * Purpose:    PostCSS pipeline for Tailwind CSS v4 (ADR-009). The plugin
 *             scans source files for utility usage and emits tree-shaken
 *             CSS; tokens themselves live in app/globals.css under @theme.
 * Dependencies: @tailwindcss/postcss (devDependency, apps/web)
 * Scope:      apps/web build.
 */

const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
