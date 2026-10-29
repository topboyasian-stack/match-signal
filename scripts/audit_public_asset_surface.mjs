#!/usr/bin/env node
/**
 * Non-production inventory for Match Signal's current Cloudflare Pages output.
 * It records paths and references only; it never prints file contents or secrets.
 */
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";

const ROOT = process.cwd();
const OUTPUT_JSON = path.join(ROOT, "PUBLIC-ASSET-SURFACE-INVENTORY.json");
const OUTPUT_MD = path.join(ROOT, "PUBLIC-ASSET-SURFACE-INVENTORY.md");
const SKIP_DIRS = new Set([".git", "node_modules", ".wrangler", ".cache", "coverage"]);
const STATIC_EXTENSIONS = new Set([
  ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".jsonl", ".csv",
  ".txt", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
  ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".md", ".py", ".yml", ".yaml",
  ".toml", ".parquet", ".gz", ".sh", ".wasm", ".map"
]);
const TEXT_EXTENSIONS = new Set([
  ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".json", ".jsonl", ".csv",
  ".txt", ".xml", ".md", ".py", ".yml", ".yaml", ".toml", ".sh"
]);

function posix(value) { return value.split(path.sep).join("/"); }
function hiddenPath(value) { return value.split("/").some(part => part.startsWith(".")); }
function category(file) {
  if (file.startsWith("functions/")) return "pages_function_source";
  if (hiddenPath(file)) return "hidden_or_special_path";
  if (STATIC_EXTENSIONS.has(path.extname(file).toLowerCase())) return "likely_static_asset";
  return "other_repository_file";
}
function safeText(value) {
  return String(value || "").replace(/[\r\n\t]+/g, " ").slice(0, 500);
}
function collectReferences(file, source) {
  const refs = new Set();
  const patterns = [
    /(?:src|href|poster|data-src)\s*=\s*["']([^"'#]+)["']/gi,
    /(?:fetch|import)\s*\(\s*["']([^"'#]+)["']/gi,
    /(?:fetch|import)\s*["']([^"'#]+)["']/gi,
    /["']((?:\.\.?\/|\/)(?:data|assets|scripts|functions|api|[a-zA-Z0-9_-]+)[^"'\s]*)["']/g
  ];
  for (const re of patterns) {
    for (const match of source.matchAll(re)) {
      const value = safeText(match[1]);
      if (!value || value.startsWith("data:") || value.startsWith("javascript:")) continue;
      refs.add(value);
    }
  }
  return [...refs].sort().map(reference => ({ from: file, reference }));
}
async function walk(directory, out = []) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && SKIP_DIRS.has(entry.name)) continue;
    const absolute = path.join(directory, entry.name);
    const relative = posix(path.relative(ROOT, absolute));
    if (entry.isDirectory()) await walk(absolute, out);
    else if (entry.isFile()) {
      const info = await stat(absolute);
      out.push({ path: relative, bytes: info.size, extension: path.extname(entry.name).toLowerCase(), category: category(relative) });
    }
  }
  return out;
}

const files = (await walk(ROOT)).sort((a, b) => a.path.localeCompare(b.path));
const references = [];
const readErrors = [];
for (const file of files) {
  if (!TEXT_EXTENSIONS.has(file.extension) || file.bytes > 5_000_000) continue;
  try {
    const source = await readFile(path.join(ROOT, file.path), "utf8");
    if ([".html", ".js", ".mjs", ".css"].includes(file.extension)) {
      references.push(...collectReferences(file.path, source));
    }
  } catch (error) {
    readErrors.push({ path: file.path, error: safeText(error?.message || error) });
  }
}
const likelyStatic = files.filter(file => file.category === "likely_static_asset");
const dataFiles = files.filter(file => file.path.startsWith("data/"));
const scriptsFiles = files.filter(file => file.path.startsWith("scripts/"));
const workflowFiles = files.filter(file => file.path.startsWith(".github/workflows/"));
const functionFiles = files.filter(file => file.category === "pages_function_source");
const referencesBySource = {};
for (const item of references) {
  (referencesBySource[item.from] ||= []).push(item.reference);
}
const report = {
  generated_at: new Date().toISOString(),
  mode: "AUDIT_ONLY_NO_DEPLOYMENT_CHANGES",
  deployment_assumption: "Cloudflare Pages output directory is repository root (.). This is a candidate inventory, not proof every path is served; confirm with HTTP checks before changing deploy rules.",
  totals: {
    repository_files: files.length,
    likely_static_asset_candidates: likelyStatic.length,
    data_files: dataFiles.length,
    scripts_files: scriptsFiles.length,
    workflow_files: workflowFiles.length,
    pages_function_source_files: functionFiles.length,
    browser_reference_edges: references.length,
    read_errors: readErrors.length
  },
  files,
  likely_static_asset_candidates: likelyStatic,
  data_files: dataFiles,
  scripts_files: scriptsFiles,
  workflow_files: workflowFiles,
  pages_function_source_files: functionFiles,
  browser_references: references,
  references_by_source: referencesBySource,
  read_errors: readErrors
};
await writeFile(OUTPUT_JSON, JSON.stringify(report, null, 2) + "\n", "utf8");
const topData = [...dataFiles].sort((a, b) => b.bytes - a.bytes).slice(0, 30);
const topStatic = [...likelyStatic].sort((a, b) => b.bytes - a.bytes).slice(0, 30);
const lines = [
  "# Match Signal Public Asset Surface Inventory",
  "",
  "- Generated: " + report.generated_at,
  "- Mode: AUDIT ONLY; no deployment changes",
  "- Assumption: Cloudflare Pages output directory is the repository root. This is a candidate inventory, not proof each file is served. Verify paths over HTTP before changing deployment rules.",
  "",
  "## Summary",
  "",
  "| Inventory | Count |",
  "| --- | ---: |",
  "| Repository files | " + report.totals.repository_files + " |",
  "| Likely static asset candidates | " + report.totals.likely_static_asset_candidates + " |",
  "| data/ files | " + report.totals.data_files + " |",
  "| scripts/ files | " + report.totals.scripts_files + " |",
  "| GitHub workflow files | " + report.totals.workflow_files + " |",
  "| Pages Function source files | " + report.totals.pages_function_source_files + " |",
  "| Browser reference edges found | " + report.totals.browser_reference_edges + " |",
  "| Text read errors | " + report.totals.read_errors + " |",
  "",
  "## Largest likely static candidates",
  "",
  "| Path | Bytes |",
  "| --- | ---: |",
  ...topStatic.map(file => "| " + file.path + " | " + file.bytes + " |"),
  "",
  "## Largest data files",
  "",
  "| Path | Bytes |",
  "| --- | ---: |",
  ...topData.map(file => "| " + file.path + " | " + file.bytes + " |"),
  "",
  "## Browser asset and data references",
  "",
  ...Object.entries(referencesBySource).sort(([a], [b]) => a.localeCompare(b)).map(([from, refs]) =>
    "- " + from + "\n" + refs.map(ref => "  - " + ref).join("\n")
  ),
  "",
  "## Next safety step",
  "",
  "Do not exclude scripts/ or data/ from production yet. First verify actual production responses and map every referenced dependency; then create a minimal public allowlist and test it on a preview deployment. No secrets or file contents are included in this report.",
  ""
];
await writeFile(OUTPUT_MD, lines.join("\n"), "utf8");
console.log(JSON.stringify({
  generated: ["PUBLIC-ASSET-SURFACE-INVENTORY.json", "PUBLIC-ASSET-SURFACE-INVENTORY.md"],
  ...report.totals,
  topStatic: topStatic.slice(0, 8).map(file => ({ path: file.path, bytes: file.bytes }))
}, null, 2));
