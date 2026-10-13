import { chromium } from "playwright";
import { appendFile, writeFile } from "node:fs/promises";
import { classifyQualifiedBestMonitor } from "./qualified_best_monitor_lib.mjs";

const target = process.env.QUALIFIED_BEST_URL || "https://match-signal.pages.dev/qualified-best.html";
const repoName = process.env.GITHUB_REPOSITORY || "topboyasian-stack/match-signal";
const token = process.env.GITHUB_TOKEN || "";
const runId = process.env.GITHUB_RUN_ID || null;
const maxAttempts = 2;
const outputPath = "qualified-best-monitor-result.json";

async function fetchScheduleGap() {
  if (!token || !repoName || !runId) {
    return { schedule_gap_status: "unknown", schedule_gap_minutes: null, schedule_gap_note: "GitHub run metadata is unavailable in this environment." };
  }
  try {
    const response = await fetch(`https://api.github.com/repos/${repoName}/actions/workflows/qualified-best-monitor.yml/runs?per_page=100`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "match-signal-qualified-best-monitor"
      },
      signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) {
      return { schedule_gap_status: "unavailable", schedule_gap_minutes: null, schedule_gap_note: `GitHub Actions run history returned HTTP ${response.status}.` };
    }
    const payload = await response.json();
    const runs = Array.isArray(payload?.workflow_runs) ? payload.workflow_runs : [];
    const current = runs.find(run => String(run.id) === String(runId));
    const eventName = String(process.env.GITHUB_EVENT_NAME || current?.event || "unknown");
    const currentStart = Date.parse(String(current?.run_started_at || current?.created_at || ""));
    const scheduled = runs
      .filter(run => run.event === "schedule" && String(run.id) !== String(runId))
      .map(run => ({ run, stamp: Date.parse(String(run.run_started_at || run.created_at || "")) }))
      .filter(item => Number.isFinite(item.stamp))
      .sort((a, b) => b.stamp - a.stamp);
    const previous = scheduled.find(item => !Number.isFinite(currentStart) || item.stamp < currentStart);

    if (!previous) {
      return {
        schedule_gap_status: "unknown",
        schedule_gap_minutes: null,
        schedule_gap_note: "No earlier cron-triggered monitor run is available yet; the baseline will be established by the first scheduled run."
      };
    }

    // Scheduled invocations compare cron-to-cron. Deploy-triggered and manual
    // invocations report the age of the last scheduled check, so frequent
    // deployments cannot mask a stalled 20-minute schedule.
    const referenceTime = eventName === "schedule" && Number.isFinite(currentStart)
      ? currentStart : Date.now();
    const gapMinutes = Math.round((referenceTime - previous.stamp) / 6000) / 10;
    return {
      schedule_gap_status: "ok",
      schedule_gap_minutes: gapMinutes,
      schedule_gap_note: eventName === "schedule"
        ? `Previous scheduled run ${previous.run.run_number ?? previous.run.id} started ${gapMinutes} minute(s) before this scheduled run.`
        : `The last scheduled run (${previous.run.run_number ?? previous.run.id}) was ${gapMinutes} minute(s) ago.`,
      previous_run_id: previous.run.id,
      previous_run_created_at: previous.run.created_at || null
    };
  } catch (error) {
    return { schedule_gap_status: "unavailable", schedule_gap_minutes: null, schedule_gap_note: String(error?.message || error || "Schedule-gap API check failed.") };
  }
}
function diagnosticFromPage(pageErrors, snapshot) {
  const dom = snapshot && typeof snapshot === "object" ? snapshot : {};
  return {
    ...dom,
    page_errors: pageErrors,
    page_url: dom.page_url || target
  };
}

async function run() {
  const startedAt = new Date().toISOString();
  const attempts = [];
  let finalSnapshot = null;
  let browser = null;

  try {
    browser = await chromium.launch({ headless: true });
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      let page = null;
      const pageErrors = [];
      try {
        page = await browser.newPage({
          viewport: { width: 1440, height: 1000 },
          locale: "en-GB",
          reducedMotion: "reduce"
        });
        page.on("pageerror", error => pageErrors.push(String(error?.message || error)));
        const separator = target.includes("?") ? "&" : "?";
        await page.goto(`${target}${separator}monitor_run=${encodeURIComponent(String(runId || "manual"))}_${attempt}`, {
          waitUntil: "domcontentloaded",
          timeout: 30000
        });
        await page.waitForFunction(() => {
          const state = window.__MATCH_SIGNAL_QUALIFIED_BEST_MONITOR__;
          return Boolean(state) && (
            state.stage === "failed" ||
            (state.stage === "completed" && state.live_quote_refresh_state !== "pending")
          );
        }, null, { timeout: 75000 });
        // Let the synchronous redraw finish before comparing the emitted gate
        // count with the actual visible rows.
        await page.waitForTimeout(200);
        const snapshot = await page.evaluate(() => {
          const source = window.__MATCH_SIGNAL_QUALIFIED_BEST_MONITOR__;
          if (!source) return null;
          return {
            ...source,
            dom_qualified_count: document.querySelectorAll("#qualifiedBestBoard .ms-qualified-best-row").length,
            dom_summary: document.querySelector("#qualifiedBestSummary")?.innerText || null,
            dom_source_status: document.querySelector("#qualifiedBestDataStatus")?.innerText || null,
            page_url: location.href
          };
        });
        finalSnapshot = diagnosticFromPage(pageErrors, snapshot);
        const provisional = classifyQualifiedBestMonitor(finalSnapshot, { nowMs: Date.now() });
        attempts.push({
          attempt,
          observed_at: new Date().toISOString(),
          status: provisional.status,
          classification: provisional.classification,
          reasons: provisional.reasons,
          diagnostic: finalSnapshot
        });
        if (provisional.status === "healthy") break;
      } catch (error) {
        attempts.push({
          attempt,
          observed_at: new Date().toISOString(),
          status: "failed",
          classification: "browser_check_failed",
          reasons: [String(error?.message || error || "Browser check failed.")],
          diagnostic: finalSnapshot
        });
      } finally {
        if (page) await page.close().catch(() => {});
      }
      if (attempt < maxAttempts) await new Promise(resolve => setTimeout(resolve, 1500));
    }
  } catch (error) {
    attempts.push({
      attempt: 0,
      observed_at: new Date().toISOString(),
      status: "failed",
      classification: "browser_start_failed",
      reasons: [String(error?.message || error || "Could not launch browser.")],
      diagnostic: null
    });
  } finally {
    if (browser) await browser.close().catch(() => {});
  }

  const schedule = await fetchScheduleGap();
  if (!finalSnapshot) {
    finalSnapshot = {
      stage: "failed",
      emitted_at: new Date().toISOString(),
      page_mode: "qualified-best",
      board_payload_loaded: false,
      selection_candidates_loaded: false,
      source_fresh: false,
      source_fallback_used: false,
      live_quote_refresh_state: "unknown",
      current_qualified_count: null,
      page_errors: [],
      error: attempts.at(-1)?.reasons?.join("; ") || "No browser snapshot was captured."
    };
  }
  Object.assign(finalSnapshot, schedule);
  finalSnapshot.page_errors = Array.isArray(finalSnapshot.page_errors) ? finalSnapshot.page_errors : [];
  const result = classifyQualifiedBestMonitor(finalSnapshot, { nowMs: Date.now() });
  const recoveredAfterRetry = result.status === "healthy" &&
    attempts.length > 1 && attempts.slice(0, -1).some(attempt => attempt.status === "failed");
  if (recoveredAfterRetry && !result.warnings.includes("PRODUCTION_CHECK_RECOVERED_AFTER_RETRY")) {
    result.warnings.push("PRODUCTION_CHECK_RECOVERED_AFTER_RETRY");
  }
  const output = {
    monitor: "Match Signal Qualified Best production monitor",
    version: 1,
    target,
    repository: repoName,
    workflow_run_id: runId,
    commit_sha: process.env.GITHUB_SHA || null,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    attempts,
    diagnostic: finalSnapshot,
    schedule,
    result
  };

  await writeFile(outputPath, JSON.stringify(output, null, 2) + "\n", "utf8");
  if (process.env.GITHUB_STEP_SUMMARY) {
    const count = result.qualified_count;
    const zeroMessage = result.classification === "valid_zero_qualified"
      ? "The qualification check completed successfully and returned zero current picks. Zero is valid; it is not treated as a monitor failure."
      : `Current qualified fixtures: ${count ?? "unknown"}.`;
    const reasons = result.reasons.length ? result.reasons.map(reason => `- ${reason}`).join("\n") : "- None";
    const warnings = result.warnings.length ? result.warnings.map(warning => `- ${warning}`).join("\n") : "- None";
    const summary = [
      "## Qualified Best production monitor",
      "",
      `- **Status:** ${result.status.toUpperCase()}`,
      `- **Classification:** ${result.classification}`,
      `- **Production URL:** ${target}`,
      `- **Current qualified fixtures:** ${count ?? "unknown"}`,
      `- **Live quote refresh:** ${finalSnapshot.live_quote_refresh_state || "unknown"}`,
      `- **Source fresh:** ${String(finalSnapshot.source_fresh ?? false)}`,
      `- **Board timestamp:** ${finalSnapshot.board_generated_at || "unavailable"}`,
      `- **Last quote verification:** ${finalSnapshot.live_quote_last_verified_at || "not required / unavailable"}`,
      `- **Scheduled-run gap:** ${schedule.schedule_gap_minutes ?? "not available"} minute(s)`,
      "",
      zeroMessage,
      "",
      "### Failure reasons",
      reasons,
      "",
      "### Warnings",
      warnings,
      "",
      "### Attempt history",
      attempts.length ? attempts.map(attempt => `- Attempt ${attempt.attempt}: ${attempt.status} (${attempt.classification}); ${(attempt.reasons || []).join("; ") || "no errors"}`).join("\\n") : "- No attempts recorded.",
      "",
      "### Candidate rejection reasons",
      "```json",
      JSON.stringify(finalSnapshot.blocker_counts || {}, null, 2),
      "```",
      "",
      `Attempts: ${attempts.length}. Full diagnostic saved as \`${outputPath}\`.`
    ].join("\n");
    await appendFile(process.env.GITHUB_STEP_SUMMARY, summary + "\n", "utf8");
  }

  console.log(JSON.stringify({
    status: result.status,
    classification: result.classification,
    qualified_count: result.qualified_count,
    reasons: result.reasons,
    warnings: result.warnings,
    schedule_gap_minutes: schedule.schedule_gap_minutes,
    output: outputPath
  }, null, 2));
  if (result.exit_code !== 0) process.exitCode = 1;
}

await run();
