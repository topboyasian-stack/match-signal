import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const redirects = await readFile(path.join(root, "_redirects"), "utf8");
assert.match(redirects, /^\/scripts\/\*\s+\/\s+404\s*$/m,
  "repository scripts must not be served from the Pages origin");
assert.match(redirects, /^\/\.github\/\*\s+\/\s+404\s*$/m,
  "workflow definitions must not be served from the Pages origin");

async function walk(dir, out = []) {
  for (const item of await readdir(dir, { withFileTypes: true })) {
    if (item.isDirectory() && [".git", "node_modules", ".github", "scripts", "functions", "data"].includes(item.name)) continue;
    const absolute = path.join(dir, item.name);
    if (item.isDirectory()) await walk(absolute, out);
    else if (item.isFile() && /\.html?$/i.test(item.name)) out.push(absolute);
  }
  return out;
}
const pages = await walk(root);
const directAssetRef = /(?:src|href|poster|data-src)\s*=\s*["']([^"'#]+)["']/gi;
const internalPaths = [];
for (const file of pages) {
  const source = await readFile(file, "utf8");
  for (const match of source.matchAll(directAssetRef)) {
    const value = String(match[1] || "").split(/[?#]/, 1)[0];
    if (/^(?:\.\.\/|\.\/)?scripts\//i.test(value) || /^\/scripts\//i.test(value) ||
        /^\/?\.github\//i.test(value)) {
      internalPaths.push({ file: path.relative(root, file), reference: value });
    }
  }
}
assert.deepEqual(internalPaths, [], "browser HTML must not depend on paths being blocked");
console.log("Internal path redirect contract passed across " + pages.length + " HTML pages.");

const previewBase = String(process.env.MATCH_SIGNAL_PREVIEW_BASE || "").trim();
if (previewBase) {
  const probes = [
    { path: "/scripts/private_ml_core.py", expected: 404 },
    { path: "/.github/workflows/live-expansion.yml", expected: 404 },
    { path: "/sport-hubs.js", expected: 200 },
  ];
  let last = [];
  let passed = false;
  for (let attempt = 0; attempt < 12; attempt++) {
    last = await Promise.all(probes.map(async probe => {
      try {
        const response = await fetch(new URL(probe.path, previewBase), {
          method: "HEAD", redirect: "manual", cache: "no-store",
          signal: AbortSignal.timeout(6000)
        });
        return { ...probe, actual: response.status };
      } catch (error) {
        return { ...probe, actual: null, error: String(error?.message || error) };
      }
    }));
    if (last.every(item => item.actual === item.expected)) { passed = true; break; }
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
  assert.ok(passed, "Cloudflare Pages preview path verification failed: " + JSON.stringify(last));
  console.log("Cloudflare preview path probes passed:", JSON.stringify(last));
}
