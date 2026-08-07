/**
 * features/research/utils/detect-language.ts
 * ------------------------------------------
 * Purpose:    Detect whether a source file is a code file (by extension)
 *             and map it to a Prism language identifier for syntax highlighting.
 * Dependencies: none
 * Scope:      Citation popover code highlighting.
 */

const CODE_EXTENSIONS: Record<string, string> = {
  py: "python",
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  swift: "swift",
  rb: "ruby",
  php: "php",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  cs: "csharp",
  scala: "scala",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  sql: "sql",
  html: "html",
  css: "css",
  scss: "scss",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",
  md: "markdown",
  toml: "toml",
  dockerfile: "dockerfile",
  graphql: "graphql",
  vue: "vue",
  svelte: "svelte",
};

export function isCodeFile(sourceRef: string): boolean {
  if (!sourceRef) return false;
  const ext = getExtension(sourceRef);
  if (ext && CODE_EXTENSIONS[ext]) return true;
  const basename = getBasename(sourceRef);
  return basename === "Dockerfile" || basename === "Makefile" || basename === ".env";
}

export function detectLanguage(sourceRef: string): string {
  if (!sourceRef) return "text";
  const ext = getExtension(sourceRef);
  if (ext && CODE_EXTENSIONS[ext]) return CODE_EXTENSIONS[ext];
  const basename = getBasename(sourceRef);
  if (basename === "Dockerfile") return "dockerfile";
  if (basename === "Makefile") return "makefile";
  return "text";
}

function getExtension(filename: string): string | null {
  const base = getBasename(filename);
  if (base.startsWith(".") && !base.slice(1).includes(".")) return null;
  const lastDot = base.lastIndexOf(".");
  if (lastDot === -1 || lastDot === 0) return null;
  return base.slice(lastDot + 1).toLowerCase();
}

function getBasename(filepath: string): string {
  const parts = filepath.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || "";
}
