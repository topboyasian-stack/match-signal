import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const workflowsDir = ".github/workflows";
const workflowFiles = fs.readdirSync(workflowsDir).filter((name) => /\.(?:yml|yaml)$/i.test(name));

const duplicatePublishers = workflowFiles.filter((name) => {
  const source = fs.readFileSync(path.join(workflowsDir, name), "utf8");
  return /uses:\s*actions\/deploy-pages@/i.test(source)
    || /(^|\n)\s*pages:\s*write\b/i.test(source)
    || (/name:\s*github-pages\b/i.test(source) && /environment:/i.test(source));
});

assert.deepEqual(
  duplicatePublishers,
  [],
  `Cloudflare Pages must be the only production site publisher; found legacy GitHub Pages workflow(s): ${duplicatePublishers.join(", ")}`,
);
assert.equal(
  fs.existsSync(path.join(workflowsDir, "deploy-pages.yml")),
  false,
  "The retired GitHub Pages publisher must not be reintroduced under its old filename.",
);
assert.equal(
  fs.existsSync("DEPLOY-VERIFY-GITHUB-PAGES.json"),
  false,
  "Do not publish a stale/competing GitHub Pages production verification record.",
);

const cloudflare = fs.readFileSync(path.join(workflowsDir, "cloudflare-pages.yml"), "utf8");
assert.match(cloudflare, /name:\s*Deploy Match Signal to Cloudflare Pages/);
assert.match(cloudflare, /https:\/\/match-signal\.pages\.dev/);

const monitor = fs.readFileSync(path.join(workflowsDir, "qualified-best-production-watch.yml"), "utf8");
assert.match(
  monitor,
  /QUALIFIED_BEST_URL:\s*https:\/\/match-signal\.pages\.dev\/qualified-best\.html/,
  "The browser monitor must inspect the canonical Cloudflare production page.",
);
assert.doesNotMatch(
  monitor,
  /topboyasian-stack\.github\.io\/match-signal/i,
  "The production browser monitor must not use the legacy GitHub Pages mirror.",
);

console.log("Cloudflare-only production hosting checks passed.");
