import { createReadStream, createWriteStream } from 'node:fs';
import { copyFile, mkdir, readdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createGzip } from 'node:zlib';
import { pipeline } from 'node:stream/promises';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(process.env.MATCH_SIGNAL_BUILD_ROOT || path.join(scriptDir, '..'));
const output = path.resolve(process.env.MATCH_SIGNAL_BUILD_OUTPUT || path.join(root, 'dist'));
const MAX_ASSET_BYTES = 25 * 1024 * 1024;

// These are model/research ledgers used by repository workflows, not public web assets.
// They stay in Git so the research pipeline can keep learning from them.
const excludedFiles = new Set([
  'data/efootball_desk_settled_observations.json',
  'data/efootball_market_research.json',
  'data/nba_live_observations.json.gz'
]);
const skippedFiles = new Set(['wrangler.toml', 'package.json', 'package-lock.json', '.gitignore']);
const skippedDirectories = new Set([
  '.git', '.github', '.wrangler', 'node_modules', 'functions', 'scripts',
  'tests', '__tests__', 'coverage', '.pytest_cache', '.venv', 'venv',
  '__pycache__', 'dist'
]);
const historyRaw = 'data/virtual_lab_history.json';
const historyGzip = 'data/virtual_lab_history.json.gz';

async function gzipFile(source, destination) {
  await mkdir(path.dirname(destination), { recursive: true });
  await pipeline(
    createReadStream(source),
    createGzip({ level: 9 }),
    createWriteStream(destination)
  );
  const compressed = await stat(destination);
  if (compressed.size > MAX_ASSET_BYTES) {
    throw new Error(
      `${historyRaw} compresses to ${(compressed.size / 1024 / 1024).toFixed(2)} MiB; ` +
      'the Virtual Lab history needs chunking or external object storage.'
    );
  }
  return compressed.size;
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

let copiedFiles = 0;
let skippedCount = 0;
let historyCompressedBytes = 0;

// The Pages Function reads the gzip route first. Generate a deployable gzip asset
// from the source ledger so the raw >25 MiB JSON never needs to be uploaded.
const rawHistoryPath = path.join(root, historyRaw);
let generatedHistoryGzip = false;
try {
  const rawStat = await stat(rawHistoryPath);
  if (rawStat.isFile()) {
    historyCompressedBytes = await gzipFile(rawHistoryPath, path.join(output, historyGzip));
    generatedHistoryGzip = true;
  }
} catch (error) {
  if (error?.code !== 'ENOENT') throw error;
}

async function copyDirectory(sourceDir, destinationDir, relativeDir = '') {
  const entries = await readdir(sourceDir, { withFileTypes: true });
  for (const entry of entries) {
    const relativePath = path.posix.join(relativeDir, entry.name);
    const sourcePath = path.join(sourceDir, entry.name);
    const destinationPath = path.join(destinationDir, entry.name);

    if (entry.isDirectory()) {
      if (skippedDirectories.has(entry.name)) {
        skippedCount += 1;
        continue;
      }
      await mkdir(destinationPath, { recursive: true });
      await copyDirectory(sourcePath, destinationPath, relativePath);
      continue;
    }

    if (!entry.isFile()) {
      skippedCount += 1;
      continue;
    }

    if (skippedFiles.has(entry.name) || excludedFiles.has(relativePath) ||
        relativePath === historyRaw ||
        (generatedHistoryGzip && relativePath === historyGzip)) {
      skippedCount += 1;
      continue;
    }

    const fileStat = await stat(sourcePath);
    if (fileStat.size > MAX_ASSET_BYTES) {
      throw new Error(
        `Unfiltered Pages asset exceeds the 25 MiB limit: ${relativePath} ` +
        `(${(fileStat.size / 1024 / 1024).toFixed(2)} MiB). ` +
        'Add it to the research-artifact exclusion list only after confirming it is not a public runtime dependency.'
      );
    }

    await mkdir(path.dirname(destinationPath), { recursive: true });
    await copyFile(sourcePath, destinationPath);
    copiedFiles += 1;
  }
}

await copyDirectory(root, output);
console.log(
  `Pages asset bundle ready: ${copiedFiles} files copied, ${skippedCount} entries excluded, ` +
  `output=${path.relative(root, output) || '.'}`
);
if (generatedHistoryGzip) {
  console.log(`Virtual Lab history compressed to ${(historyCompressedBytes / 1024 / 1024).toFixed(2)} MiB.`);
}
