import {
  authorizeAnalystRequest,
  jsonResponse,
  readJsonBody
} from "../../_shared/analyst.mjs";

const EVIDENCE_KEY = "private-cross-sport-market-reassessment-v1";
const MAX_BODY_BYTES = 12 * 1024 * 1024;
const MAX_RECORDS = 12000;
const SUPPORTED_SPORTS = new Set(["football", "tennis", "virtual", "basketball"]);

async function readDocument(env) {
  const raw = await env.MATCH_SIGNAL_ANALYST_STORE.get(EVIDENCE_KEY);
  if (!raw) return null;
  let value;
  try { value = JSON.parse(raw); }
  catch { throw new Error("PRIVATE_EVIDENCE_INVALID_JSON"); }
  if (!value || value.record_type !== "cross_sport_market_reassessment" || !Array.isArray(value.records)) {
    throw new Error("PRIVATE_EVIDENCE_INVALID_SHAPE");
  }
  return value;
}

function validateDocument(value) {
  const errors = [];
  if (!value || typeof value !== "object" || Array.isArray(value)) return ["root must be an object"];
  if (value.record_type !== "cross_sport_market_reassessment") errors.push("record_type is invalid");
  if (value.mode !== "PAPER_ONLY") errors.push("mode must be PAPER_ONLY");
  if (!Array.isArray(value.records)) return errors.concat("records must be an array");
  if (value.records.length > MAX_RECORDS) errors.push("record limit exceeded");
  const ids = new Set();
  if (value.primary_predictions !== undefined && !Array.isArray(value.primary_predictions)) errors.push("primary_predictions must be an array");
  const primaryIds = new Set();
  for (const [i, row] of (Array.isArray(value.primary_predictions) ? value.primary_predictions : []).entries()) {
    const where = "primary_predictions[" + i + "]";
    if (!row || typeof row !== "object" || Array.isArray(row)) { errors.push(where + " must be an object"); continue; }
    if (typeof row.fixture_id !== "string" || !/^[a-f0-9]{24}$/.test(row.fixture_id)) errors.push(where + ".fixture_id is invalid");
    else if (primaryIds.has(row.fixture_id)) errors.push(where + ".fixture_id is duplicated");
    else primaryIds.add(row.fixture_id);
    if (!SUPPORTED_SPORTS.has(row.sport)) errors.push(where + ".sport is unsupported");
    if (typeof row.event_id !== "string" || !row.event_id.trim() || row.event_id.length > 200) errors.push(where + ".event_id is invalid");
    if (row.prediction_role !== "PRIMARY") errors.push(where + ".prediction_role must be PRIMARY");
    if (!["FROZEN", "UNCLASSIFIED"].includes(row.primary_status)) errors.push(where + ".primary_status is invalid");
    if (row.primary_status === "FROZEN" && (!row.primary_market || !row.primary_pick)) errors.push(where + " frozen primary requires market and pick");
    if (row.primary_probability !== null && row.primary_probability !== undefined && (typeof row.primary_probability !== "number" || !Number.isFinite(row.primary_probability) || row.primary_probability < 0 || row.primary_probability > 1)) errors.push(where + ".primary_probability is invalid");
    if (row.settlement_status !== "PENDING" && row.settlement_status !== "SETTLED" && row.settlement_status !== "UNCLASSIFIED") errors.push(where + ".settlement_status is invalid");
  }
  for (let i = 0; i < value.records.length; i += 1) {
    const row = value.records[i];
    const where = "records[" + i + "]";
    if (!row || typeof row !== "object" || Array.isArray(row)) { errors.push(where + " must be an object"); continue; }
    if (typeof row.snapshot_id !== "string" || !/^[a-f0-9]{24}$/.test(row.snapshot_id)) errors.push(where + ".snapshot_id is invalid");
    else if (ids.has(row.snapshot_id)) errors.push(where + ".snapshot_id is duplicated");
    else ids.add(row.snapshot_id);
    if (!SUPPORTED_SPORTS.has(row.sport)) errors.push(where + ".sport is unsupported");
    if (typeof row.event_id !== "string" || !row.event_id.trim() || row.event_id.length > 200) errors.push(where + ".event_id is invalid");
    if (typeof row.market !== "string" || !row.market.trim() || row.market.length > 80) errors.push(where + ".market is invalid");
    if (typeof row.pick !== "string" || !row.pick.trim() || row.pick.length > 40) errors.push(where + ".pick is invalid");
    if (typeof row.quote_timestamp !== "string" || !Number.isFinite(Date.parse(row.quote_timestamp))) errors.push(where + ".quote_timestamp is invalid");
    if (typeof row.start_time !== "string" || !Number.isFinite(Date.parse(row.start_time))) errors.push(where + ".start_time is invalid");
    if (typeof row.model_probability !== "number" || !Number.isFinite(row.model_probability) || row.model_probability < 0 || row.model_probability > 1) errors.push(where + ".model_probability is invalid");
    if (typeof row.bookmaker_odds !== "number" || !Number.isFinite(row.bookmaker_odds) || row.bookmaker_odds <= 1) errors.push(where + ".bookmaker_odds is invalid");
    if (row.settlement_status !== "PENDING" && row.settlement_status !== "SETTLED") errors.push(where + ".settlement_status is invalid");
  }
  return errors;
}

export async function onRequestGet(context) {
  const access = await authorizeAnalystRequest(context);
  if (access.response) return access.response;
  try {
    const document = await readDocument(context.env);
    return jsonResponse({
      status: "OK",
      revision: document && document.updated_at ? document.updated_at : "none",
      document: document
    });
  } catch {
    return jsonResponse({ error: "PRIVATE_MARKET_EVIDENCE_UNAVAILABLE" }, 500);
  }
}

export async function onRequestPut(context) {
  const access = await authorizeAnalystRequest(context);
  if (access.response) return access.response;
  const parsed = await readJsonBody(context.request, MAX_BODY_BYTES);
  if (parsed.error) return jsonResponse({ error: parsed.error }, parsed.error === "REQUEST_TOO_LARGE" ? 413 : 400);
  const incoming = parsed.body;
  const errors = validateDocument(incoming);
  if (errors.length) return jsonResponse({ error: "INVALID_PRIVATE_MARKET_EVIDENCE", validation_errors: errors.slice(0, 50) }, 400);

  // Primary and alternative records share one revision-checked private evidence document.
  const expectedRevision = context.request.headers.get("If-Match");
  if (!expectedRevision) return jsonResponse({ error: "PRECONDITION_REQUIRED", message: "Restore the private evidence ledger before publishing updates." }, 428);
  let current;
  try { current = await readDocument(context.env); }
  catch { return jsonResponse({ error: "PRIVATE_MARKET_EVIDENCE_UNAVAILABLE" }, 500); }
  const currentRevision = current && current.updated_at ? current.updated_at : "none";
  if (expectedRevision !== currentRevision) {
    return jsonResponse({ error: "LEDGER_REVISION_CONFLICT", current_revision: currentRevision }, 409);
  }

  // Snapshot identity/quote/model fields are immutable. Only settlement fields,
  // the generated timestamp and the rolling evidence collection metadata can change.
  if (current) {
    // Fixture-level primary identity is append-only; only its first valid settlement may be recorded.
    const incomingPrimary = new Map((incoming.primary_predictions || []).map(row => [row.fixture_id, row]));
    for (const oldRow of current.primary_predictions || []) {
      const next = incomingPrimary.get(oldRow.fixture_id);
      if (!next) return jsonResponse({ error: "FROZEN_PRIMARY_REMOVED", fixture_id: oldRow.fixture_id }, 409);
      for (const key of ["sport", "event_id", "start_time", "prediction_timestamp", "primary_status", "primary_market", "primary_pick", "primary_line", "primary_probability", "primary_source", "prediction_role"]) {
        if (JSON.stringify(oldRow[key] ?? null) !== JSON.stringify(next[key] ?? null)) return jsonResponse({ error: "FROZEN_PRIMARY_CHANGED", fixture_id: oldRow.fixture_id, field: key }, 409);
      }
      if (oldRow.settlement_status === "SETTLED" && (oldRow.settlement_result !== next.settlement_result || oldRow.settled_at !== next.settled_at)) return jsonResponse({ error: "FROZEN_PRIMARY_SETTLEMENT_CHANGED", fixture_id: oldRow.fixture_id }, 409);
    }
    const byId = new Map(incoming.records.map(row => [row.snapshot_id, row]));
    for (const oldRow of current.records) {
      const newRow = byId.get(oldRow.snapshot_id);
      if (!newRow) {
        // The rolling 12k-row bound permits trimming old pending observations only.
        if (current.records.length < MAX_RECORDS || oldRow.settlement_status === "SETTLED") {
          return jsonResponse({ error: "IMMUTABLE_EVIDENCE_ROW_REMOVED", snapshot_id: oldRow.snapshot_id }, 409);
        }
        continue;
      }
      for (const key of ["sport", "event_id", "start_time", "market", "line", "pick", "model_probability", "bookmaker_odds", "quote_timestamp", "sportybet_event_id", "sportybet_market_id", "sportybet_outcome_id"]) {
        if (JSON.stringify(oldRow[key] ?? null) !== JSON.stringify(newRow[key] ?? null)) {
          return jsonResponse({ error: "IMMUTABLE_EVIDENCE_FIELD_CHANGED", snapshot_id: oldRow.snapshot_id, field: key }, 409);
        }
      }
      if (oldRow.settlement_status === "SETTLED" && (
        oldRow.settlement_result !== newRow.settlement_result ||
        oldRow.settled_at !== newRow.settled_at
      )) {
        return jsonResponse({ error: "SETTLED_EVIDENCE_IMMUTABLE", snapshot_id: oldRow.snapshot_id }, 409);
      }
    }
  }

  const document = Object.assign({}, incoming, {
    record_type: "cross_sport_market_reassessment",
    mode: "PAPER_ONLY",
    updated_at: new Date().toISOString(),
    record_count: incoming.records.length
  });
  try {
    await context.env.MATCH_SIGNAL_ANALYST_STORE.put(EVIDENCE_KEY, JSON.stringify(document));
    return jsonResponse({
      status: "SAVED",
      revision: document.updated_at,
      record_count: document.records.length
    });
  } catch {
    return jsonResponse({ error: "PRIVATE_MARKET_EVIDENCE_SAVE_FAILED" }, 500);
  }
}
