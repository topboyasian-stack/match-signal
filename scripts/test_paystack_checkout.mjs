import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const read = p => readFile(path.join(root, p), 'utf8');
const redirects = await read('_redirects');
assert.match(redirects, /^\/scripts\/\*\s+\/\s+404\s*$/m);
assert.match(redirects, /^\/\.github\/\*\s+\/\s+404\s*$/m);

const init = await read('functions/api/payments/initialize.js');
const verify = await read('functions/api/payments/verify.js');
const webhook = await read('functions/api/payments/webhook.js');
const auth = await read('functions/_lib/api-auth.js');
const schema = await read('migrations/0001_match_signal_payments.sql');
const checkout = await read('api-access.html');
const success = await read('payment-success.html');
const docs = await read('docs/PAYSTACK_API_LAUNCH.md');

assert.match(init, /api\.paystack\.co\/transaction\/initialize/);
assert.match(init, /MATCH_SIGNAL_API_MONTHLY_PRICE_KOBO\s*\|\|\s*'500000'/);
assert.doesNotMatch(init, /body\.amount|body\.price/);
assert.match(verify, /api\.paystack\.co\/transaction\/verify/);
assert.match(verify, /verified\.data\?\.status!=='success'/);
assert.match(verify, /verified\.data\?\.currency!=='NGN'/);
assert.match(verify, /encryptKey/);
assert.match(webhook, /HMAC/);
assert.match(webhook, /SHA-512/);
assert.match(webhook, /x-paystack-signature/);
assert.match(auth, /ms_api_keys/);
assert.match(auth, /expires_at > datetime/);
assert.match(schema, /CREATE TABLE IF NOT EXISTS ms_payments/);
assert.match(schema, /CREATE TABLE IF NOT EXISTS ms_api_keys/);
assert.match(schema, /key_ciphertext TEXT NOT NULL/);
assert.match(checkout, /\/api\/payments\/initialize/);
assert.match(success, /\/api\/payments\/verify/);
assert.match(docs, /PAYSTACK_SECRET_KEY/);
assert.match(docs, /MATCH_SIGNAL_DB/);

async function walk(dir) {
  const out = [];
  for (const item of await readdir(path.join(root, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, item.name);
    if (item.isDirectory()) out.push(...await walk(rel));
    else if (item.isFile() && item.name.endsWith('.js')) out.push(rel);
  }
  return out;
}
async function walkHtml(dir, out = []) {
  for (const item of await readdir(path.join(root, dir), { withFileTypes: true })) {
    if (item.isDirectory() && ['.git', 'node_modules', '.github', 'scripts', 'functions', 'data'].includes(item.name)) continue;
    const rel = path.posix.join(dir, item.name);
    if (item.isDirectory()) await walkHtml(rel, out);
    else if (item.isFile() && /\.html?$/i.test(item.name)) out.push(rel);
  }
  return out;
}
const htmlFiles = await walkHtml('.');
const directAssetRef = /(?:src|href|poster|data-src)\s*=\s*["']([^"'#]+)["']/gi;
for (const file of htmlFiles) {
  const source = await read(file);
  for (const match of source.matchAll(directAssetRef)) {
    const value = String(match[1] || '').split(/[?#]/, 1)[0];
    assert.ok(!/^(?:\.\.\/|\.\/)?scripts\//i.test(value) && !/^\/scripts\//i.test(value) && !/^\/?\.github\//i.test(value),
      `browser HTML ${file} must not depend on blocked internal path: ${value}`);
  }
}
const functionFiles = await walk('functions');
assert.ok(functionFiles.length >= 7, 'expected payment and API function files');
console.log('Payment/security contract checks passed. HTML pages scanned:', htmlFiles.length, 'JavaScript files to syntax-check:', functionFiles.length);
