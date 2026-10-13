export function classifyQualifiedBestMonitor(snapshot, options = {}) {
  const nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
  const maxScheduleGapMinutes = Number.isFinite(options.maxScheduleGapMinutes)
    ? options.maxScheduleGapMinutes : 35;
  const problems = [];
  const warnings = [];

  if (!snapshot || typeof snapshot !== "object") {
    return { status: "failed", classification: "check_failed", exit_code: 1,
      reasons: ["NO_MONITOR_SNAPSHOT"], warnings: [] };
  }

  if (snapshot.stage !== "completed") {
    problems.push(snapshot.stage === "failed" ? "QUALIFICATION_RENDER_FAILED" : "QUALIFICATION_CHECK_INCOMPLETE");
  }
  if (snapshot.board_payload_loaded !== true) problems.push("CANONICAL_BOARD_FETCH_FAILED");
  if (snapshot.selection_candidates_loaded !== true) problems.push("SELECTION_CANDIDATES_FETCH_FAILED");
  if (snapshot.source_fresh !== true) problems.push("SOURCE_DATA_STALE_OR_TIMESTAMP_INVALID");
  // A fallback list is useful for browsing but assigns a synthetic timestamp.
  // It must never certify a current live qualification check.
  if (snapshot.source_fallback_used === true) problems.push("CANONICAL_BOARD_EMPTY_OR_UNAVAILABLE_FALLBACK_USED");

  const quoteState = String(snapshot.live_quote_refresh_state || "unknown");
  if (quoteState !== "complete") {
    problems.push("LIVE_QUOTE_REFRESH_" + quoteState.toUpperCase());
  }

  const requiredQuoteRows = Number(snapshot.required_quote_rows || 0);
  if (Number.isFinite(requiredQuoteRows) && requiredQuoteRows > 0) {
    const verifiedAt = Date.parse(String(snapshot.live_quote_last_verified_at || ""));
    if (!Number.isFinite(verifiedAt)) {
      problems.push("REQUIRED_QUOTES_HAVE_NO_VERIFICATION_TIMESTAMP");
    } else {
      const ageSeconds = (nowMs - verifiedAt) / 1000;
      if (ageSeconds < -120 || ageSeconds > 15 * 60) {
        problems.push("LIVE_QUOTE_VERIFICATION_TIMESTAMP_STALE_OR_FUTURE");
      }
    }
  }

  const pageErrors = Array.isArray(snapshot.page_errors) ? snapshot.page_errors : [];
  if (pageErrors.length) problems.push("BROWSER_RUNTIME_ERRORS");

  const gap = Number(snapshot.schedule_gap_minutes);
  if (Number.isFinite(gap) && gap > maxScheduleGapMinutes) {
    problems.push("MONITOR_SCHEDULE_GAP_EXCEEDED");
  } else if (snapshot.schedule_gap_status === "unknown" || snapshot.schedule_gap_status === "unavailable") {
    warnings.push("MONITOR_SCHEDULE_GAP_COULD_NOT_BE_VERIFIED");
  }

  const rawQualifiedCount = Number(snapshot.current_qualified_count);
  const qualifiedCount = Number.isFinite(rawQualifiedCount) && rawQualifiedCount >= 0
    ? Math.floor(rawQualifiedCount) : null;
  if (qualifiedCount === null) problems.push("QUALIFIED_COUNT_MISSING_OR_INVALID");

  const status = problems.length ? "failed" : "healthy";
  return {
    status,
    classification: status === "failed" ? "check_failed" : qualifiedCount === 0 ? "valid_zero_qualified" : "qualified_fixtures_present",
    exit_code: status === "failed" ? 1 : 0,
    qualified_count: qualifiedCount,
    reasons: [...new Set(problems)],
    warnings
  };
}
