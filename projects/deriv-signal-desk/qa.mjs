#!/usr/bin/env node
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import assert from "node:assert/strict";

const root = new URL("./", import.meta.url);
const html = readFileSync(new URL("./index.html", root), "utf8");
const headers = readFileSync(new URL("./_headers", root), "utf8");

function check(name, test) {
  assert.ok(test, name);
  console.log("PASS", name);
}

check("version is explicitly stamped Build 0.5", html.includes("Build 0.5"));
check("current Deriv public WebSocket endpoint exists", html.includes("wss://api.derivws.com/trading/v1/options/ws/public"));
check("legacy WebSocket fallbacks exist", html.includes("wss://ws.binaryws.com/websockets/v3") && html.includes("wss://ws.derivws.com/websockets/v3"));
check("new Deriv symbol schema is normalized", html.includes("underlying_symbol_name") && html.includes("underlying_symbol"));
check("signals are based on completed candles", html.includes("finalIndex=bars.length-2"));
check("green BUY and red SELL arrow labels are present", html.includes("BUY") && html.includes("SELL") && html.includes("sig.type==='buy'"));
check("read-only source has no known order submission methods", !/buy_contract_for_multiple_accounts|sell_contract_for_multiple_accounts|place_order|cancel_order|proposal_open_contract|trading_platform_investor_password/.test(html));
check("the deployed CSP explicitly allows the Deriv public-data endpoints", headers.includes("wss://api.derivws.com") && headers.includes("wss://ws.binaryws.com") && headers.includes("wss://ws.derivws.com"));
check("page labels manual-only operation", html.includes("Manual execution only"));

const match = html.match(/<script>([\s\S]*?)<\/script>/i);
assert.ok(match, "inline dashboard script exists");
const tempDir = mkdtempSync(join(tmpdir(), "deriv-desk-qa-"));
const scriptPath = join(tempDir, "dashboard.js");
try {
  writeFileSync(scriptPath, match[1], "utf8");
  const result = spawnSync(process.execPath, ["--check", scriptPath], { encoding: "utf8" });
  assert.equal(result.status, 0, `inline JavaScript syntax check failed: ${result.stderr || result.stdout}`);
  console.log("PASS inline dashboard JavaScript syntax");
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}

console.log("Static QA completed. Browser-to-Deriv connectivity and chart rendering must still be smoke-tested in the deployed browser.");
