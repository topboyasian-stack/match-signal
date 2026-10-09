export const REVIEW_KEY = "private-user-ticket-review-v1";
export const MAX_REVIEW_BYTES = 250000;
export const AI_DAILY_LIMIT = 25;
export const DEFAULT_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast";
export const VALID_PICKS = new Set(["over", "under"]);
export const VALID_OUTCOMES = new Set(["PENDING", "WON", "LOST", "VOID"]);
export const VALID_MARKET = "total_goals_over_under";

export function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status: status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store, max-age=0",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Vary": "Origin"
    }
  });
}

function tokenEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string" || !left || !right) return false;
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    const a = left.charCodeAt(i % left.length) || 0;
    const b = right.charCodeAt(i % right.length) || 0;
    difference |= a ^ b;
  }
  return difference === 0;
}

export async function authorizeAnalystRequest(context) {
  const origin = context.request.headers.get("Origin");
  if (origin && origin !== new URL(context.request.url).origin) {
    return { response: jsonResponse({ error: "ORIGIN_NOT_ALLOWED" }, 403) };
  }
  const expected = context.env.MATCH_SIGNAL_ANALYST_TOKEN;
  if (typeof expected !== "string" || expected.length < 32) {
    return { response: jsonResponse({ error: "ANALYST_NOT_CONFIGURED", message: "Configure the private analyst token in Cloudflare before use." }, 503) };
  }
  const header = context.request.headers.get("Authorization") || "";
  const supplied = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!tokenEqual(expected, supplied)) return { response: jsonResponse({ error: "UNAUTHORIZED" }, 401) };
  if (!context.env.MATCH_SIGNAL_ANALYST_STORE) {
    return { response: jsonResponse({ error: "ANALYST_STORAGE_NOT_CONFIGURED", message: "Bind a dedicated private KV namespace named MATCH_SIGNAL_ANALYST_STORE, then redeploy." }, 503) };
  }
  return { response: null };
}

export async function readJsonBody(request, maxBytes = MAX_REVIEW_BYTES) {
  const declaredSize = Number(request.headers.get("Content-Length") || 0);
  if (declaredSize > maxBytes) return { error: "REQUEST_TOO_LARGE" };
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > maxBytes) return { error: "REQUEST_TOO_LARGE" };
  try { return { body: JSON.parse(raw) }; }
  catch { return { error: "INVALID_JSON" }; }
}

export function emptyReviewDocument(now = new Date().toISOString()) {
  return { schema_version: 1, record_type: "private_user_ticket_review", mode: "PRIVATE_USER_EVIDENCE", updated_at: now, tickets: [] };
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}
function validDateTime(value) {
  return typeof value === "string" && value.trim() !== "" && Number.isFinite(Date.parse(value));
}
function validRef(value) {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value);
}
function checkKnownKeys(value, allowed, where, errors) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  if (Object.keys(value).some(function(key) { return !allowed.has(key); })) {
    errors.push(where + " contains unsupported properties");
  }
}
function validateSelection(value, where, errors) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    errors.push(where + " must be an object");
    return;
  }
  checkKnownKeys(value, new Set(["market", "pick", "line", "odds"]), where, errors);
  if (value.market !== VALID_MARKET) errors.push(where + ".market is invalid");
  if (!VALID_PICKS.has(value.pick)) errors.push(where + ".pick is invalid");
  if (!finiteNumber(value.line) || value.line < 0) errors.push(where + ".line is invalid");
  if (!finiteNumber(value.odds) || value.odds <= 1) errors.push(where + ".odds is invalid");
}

export function validateReviewDocument(document) {
  const errors = [];
  if (!document || typeof document !== "object" || Array.isArray(document)) return ["root must be an object"];
  if (document.schema_version !== 1) errors.push("schema_version must be 1");
  if (document.record_type !== "private_user_ticket_review") errors.push("record_type is invalid");
  if (document.mode !== "PRIVATE_USER_EVIDENCE") errors.push("mode is invalid");
  checkKnownKeys(document, new Set(["schema_version", "record_type", "mode", "updated_at", "tickets"]), "root", errors);
  if (!validDateTime(document.updated_at)) errors.push("updated_at must be a date-time");
  if (!Array.isArray(document.tickets)) return errors.concat("tickets must be an array");
  if (document.tickets.length > 1000) errors.push("tickets exceeds the safety limit");
  const ticketRefs = new Set();

  document.tickets.forEach(function(ticket, ti) {
    const where = "tickets[" + ti + "]";
    if (!ticket || typeof ticket !== "object" || Array.isArray(ticket)) {
      errors.push(where + " must be an object");
      return;
    }
    checkKnownKeys(ticket, new Set(["ticket_ref", "captured_at", "reported_ticket_outcome", "stake", "total_odds", "total_return", "currency", "legs"]), where, errors);
    if (!validRef(ticket.ticket_ref)) errors.push(where + ".ticket_ref is invalid");
    else if (ticketRefs.has(ticket.ticket_ref)) errors.push(where + " has a duplicate ticket_ref");
    else ticketRefs.add(ticket.ticket_ref);
    if (!validDateTime(ticket.captured_at)) errors.push(where + ".captured_at must be a date-time");
    if (!VALID_OUTCOMES.has(ticket.reported_ticket_outcome)) errors.push(where + ".reported_ticket_outcome is invalid");
    for (const item of [["stake", 0, false], ["total_return", 0, false], ["total_odds", 1, true]]) {
      const key = item[0], minimum = item[1], exclusive = item[2], value = ticket[key];
      if (value !== undefined && value !== null && (!finiteNumber(value) || (exclusive ? value <= minimum : value < minimum))) errors.push(where + "." + key + " is invalid");
    }
    if (ticket.currency !== undefined && (typeof ticket.currency !== "string" || ticket.currency.length > 8)) errors.push(where + ".currency is invalid");
    if (!Array.isArray(ticket.legs) || ticket.legs.length < 1 || ticket.legs.length > 50) {
      errors.push(where + ".legs must contain 1 to 50 legs");
      return;
    }
    const legRefs = new Set();
    ticket.legs.forEach(function(leg, li) {
      const lw = where + ".legs[" + li + "]";
      if (!leg || typeof leg !== "object" || Array.isArray(leg)) {
        errors.push(lw + " must be an object");
        return;
      }
      checkKnownKeys(leg, new Set(["leg_ref", "product", "competition", "match", "event_id", "kickoff_at", "desk_snapshot", "actual_selection", "final_score", "settled_at"]), lw, errors);
      if (!validRef(leg.leg_ref)) errors.push(lw + ".leg_ref is invalid");
      else if (legRefs.has(leg.leg_ref)) errors.push(lw + " has a duplicate leg_ref");
      else legRefs.add(leg.leg_ref);
      if (typeof leg.product !== "string" || !leg.product.trim() || leg.product.length > 80) errors.push(lw + ".product is required");
      if (typeof leg.match !== "string" || !leg.match.trim() || leg.match.length > 240) errors.push(lw + ".match is required");
      if (leg.competition !== undefined && (typeof leg.competition !== "string" || leg.competition.length > 120)) errors.push(lw + ".competition is invalid");
      if (leg.event_id !== undefined && (typeof leg.event_id !== "string" || leg.event_id.length > 160)) errors.push(lw + ".event_id is invalid");
      if (leg.kickoff_at !== undefined && !validDateTime(leg.kickoff_at)) errors.push(lw + ".kickoff_at is invalid");
      validateSelection(leg.actual_selection, lw + ".actual_selection", errors);
      if (leg.desk_snapshot !== undefined && leg.desk_snapshot !== null) {
        const desk = leg.desk_snapshot;
        if (!desk || typeof desk !== "object" || Array.isArray(desk)) errors.push(lw + ".desk_snapshot must be an object");
        else {
          checkKnownKeys(desk, new Set(["prediction_id", "model_version", "market", "pick", "line", "odds", "model_probability", "captured_at"]), lw + ".desk_snapshot", errors);
          if (desk.market !== VALID_MARKET) errors.push(lw + ".desk_snapshot.market is invalid");
          if (!VALID_PICKS.has(desk.pick)) errors.push(lw + ".desk_snapshot.pick is invalid");
          if (!finiteNumber(desk.line) || desk.line < 0) errors.push(lw + ".desk_snapshot.line is invalid");
          if (desk.odds !== undefined && desk.odds !== null && (!finiteNumber(desk.odds) || desk.odds <= 1)) errors.push(lw + ".desk_snapshot.odds is invalid");
          if (desk.model_probability !== undefined && desk.model_probability !== null && (!finiteNumber(desk.model_probability) || desk.model_probability < 0 || desk.model_probability > 1)) errors.push(lw + ".desk_snapshot.model_probability is invalid");
          if (!validDateTime(desk.captured_at)) errors.push(lw + ".desk_snapshot.captured_at must be a date-time");
          if (desk.prediction_id !== undefined && (typeof desk.prediction_id !== "string" || desk.prediction_id.length > 160)) errors.push(lw + ".desk_snapshot.prediction_id is invalid");
          if (desk.model_version !== undefined && (typeof desk.model_version !== "string" || desk.model_version.length > 100)) errors.push(lw + ".desk_snapshot.model_version is invalid");
        }
      }
      if (leg.final_score !== undefined && leg.final_score !== null) {
        const score = leg.final_score;
        if (!score || typeof score !== "object" || Array.isArray(score)) errors.push(lw + ".final_score must be an object");
        else {
          checkKnownKeys(score, new Set(["home", "away"]), lw + ".final_score", errors);
          for (const side of ["home", "away"]) if (!finiteNumber(score[side]) || score[side] < 0) errors.push(lw + ".final_score." + side + " is invalid");
        }
      }
      if (leg.settled_at !== undefined && leg.settled_at !== null && !validDateTime(leg.settled_at)) errors.push(lw + ".settled_at is invalid");
    });
  });
  return errors;
}

export function evaluatePick(pick, line, score) {
  if (!score || !finiteNumber(score.home) || !finiteNumber(score.away) || !finiteNumber(line)) return null;
  const total = score.home + score.away;
  if (Math.abs(total - line) < 1e-9) return "PUSH";
  if (pick === "over") return total > line ? "WON" : "LOST";
  if (pick === "under") return total < line ? "WON" : "LOST";
  return null;
}

export function classifyLineAdjustment(desk, actual) {
  if (!desk || typeof desk !== "object") return "desk_snapshot_missing";
  if (!VALID_PICKS.has(desk.pick) || !finiteNumber(desk.line)) return "desk_snapshot_incomplete";
  if (desk.pick !== actual.pick) return "side_changed";
  if (Math.abs(desk.line - actual.line) < 1e-9) return "unchanged";
  const easier = actual.pick === "over" ? actual.line < desk.line : actual.line > desk.line;
  return easier ? "user_line_easier" : "user_line_harder";
}

export function analyzeLeg(leg) {
  const actual = leg.actual_selection, desk = leg.desk_snapshot;
  const actualResult = evaluatePick(actual.pick, actual.line, leg.final_score);
  const deskResult = desk ? evaluatePick(desk.pick, desk.line, leg.final_score) : null;
  let counterfactual = "not_comparable";
  if (actualResult !== null && deskResult !== null) {
    if (actualResult === "WON" && deskResult !== "WON") counterfactual = "actual_selection_won_desk_did_not";
    else if (deskResult === "WON" && actualResult !== "WON") counterfactual = "desk_selection_won_actual_did_not";
    else if (actualResult === "WON" && deskResult === "WON") counterfactual = "both_won";
    else if (actualResult === "PUSH" || deskResult === "PUSH") counterfactual = "at_least_one_push";
    else counterfactual = "neither_won";
  }
  return {
    product: String(leg.product || "unknown").trim().toLowerCase(),
    actual_pick: actual.pick, actual_line: Number(actual.line), actual_odds: Number(actual.odds),
    actual_result: actualResult, desk_pick: desk ? desk.pick : null,
    desk_line: desk && finiteNumber(desk.line) ? Number(desk.line) : null,
    desk_result: deskResult, line_adjustment: classifyLineAdjustment(desk, actual), counterfactual: counterfactual
  };
}

export function summarizeReviewDocument(document) {
  const analyses = [];
  for (const ticket of document.tickets || []) for (const leg of ticket.legs || []) analyses.push(analyzeLeg(leg));
  const outcomes = { WON: 0, LOST: 0, PUSH: 0, UNSETTLED_OR_MISSING_SCORE: 0 };
  const lineAdjustments = {}, groups = new Map(), comparisons = {};
  for (const item of analyses) {
    if (item.actual_result === null) outcomes.UNSETTLED_OR_MISSING_SCORE += 1;
    else outcomes[item.actual_result] += 1;
    lineAdjustments[item.line_adjustment] = (lineAdjustments[item.line_adjustment] || 0) + 1;
    const key = JSON.stringify([item.product, item.actual_pick, item.actual_line]);
    if (!groups.has(key)) groups.set(key, { product: item.product, pick: item.actual_pick, line: item.actual_line, settled_non_push: 0, wins: 0, losses: 0, pushes: 0 });
    const group = groups.get(key);
    if (item.actual_result === "WON") { group.settled_non_push += 1; group.wins += 1; }
    else if (item.actual_result === "LOST") { group.settled_non_push += 1; group.losses += 1; }
    else if (item.actual_result === "PUSH") group.pushes += 1;
    if (item.counterfactual !== "not_comparable") {
      comparisons.comparable_legs = (comparisons.comparable_legs || 0) + 1;
      comparisons[item.counterfactual] = (comparisons[item.counterfactual] || 0) + 1;
    }
  }
  const exactLineSummary = Array.from(groups.values()).map(function(group) {
    group.hit_rate_excluding_pushes = group.settled_non_push ? Number((group.wins / group.settled_non_push).toFixed(4)) : null;
    return group;
  }).sort(function(a, b) {
    return a.product.localeCompare(b.product) || a.pick.localeCompare(b.pick) || a.line - b.line;
  });
  const n = outcomes.WON + outcomes.LOST;
  return {
    schema_version: 1, mode: "PRIVATE_USER_EVIDENCE", privacy: "AGGREGATE_ONLY",
    ticket_count: (document.tickets || []).length, leg_count: analyses.length,
    scored_leg_count: outcomes.WON + outcomes.LOST + outcomes.PUSH, actual_selection_outcomes: outcomes,
    actual_leg_hit_rate_excluding_pushes: n ? Number((outcomes.WON / n).toFixed(4)) : null,
    line_adjustments: Object.fromEntries(Object.entries(lineAdjustments).sort()),
    desk_vs_actual_same_score_comparison: Object.fromEntries(Object.entries(comparisons).sort()),
    exact_product_pick_line: exactLineSummary,
    interpretation_guard: "Descriptive evidence from user-selected tickets only; selection-biased and not a standalone model-validation sample. Do not update model parameters from this summary alone."
  };
}

export function privateModelTicketContext(document, limit = 8) {
  return [...(document.tickets || [])].sort(function(a, b) {
    return String(b.captured_at || "").localeCompare(String(a.captured_at || ""));
  }).slice(0, limit).map(function(ticket, index) {
    return {
      recent_ticket_number: index + 1, captured_at: ticket.captured_at,
      reported_ticket_outcome: ticket.reported_ticket_outcome,
      stake: ticket.stake == null ? null : ticket.stake,
      total_odds: ticket.total_odds == null ? null : ticket.total_odds,
      total_return: ticket.total_return == null ? null : ticket.total_return,
      legs: (ticket.legs || []).map(function(leg) {
        const analysis = analyzeLeg(leg);
        return {
          product: leg.product, competition: leg.competition || null, match: leg.match,
          kickoff_at: leg.kickoff_at || null, actual_selection: leg.actual_selection,
          desk_snapshot: leg.desk_snapshot || null, final_score: leg.final_score || null,
          actual_result: analysis.actual_result, desk_result_on_same_score: analysis.desk_result,
          line_adjustment: analysis.line_adjustment, counterfactual: analysis.counterfactual
        };
      })
    };
  });
}

export async function loadPrivateDocument(env) {
  const raw = await env.MATCH_SIGNAL_ANALYST_STORE.get(REVIEW_KEY);
  if (!raw) return emptyReviewDocument("1970-01-01T00:00:00.000Z");
  let document;
  try { document = JSON.parse(raw); } catch { throw new Error("PRIVATE_RECORDS_INVALID_JSON"); }
  if (validateReviewDocument(document).length) throw new Error("PRIVATE_RECORDS_FAIL_VALIDATION");
  return document;
}

export async function consumeDailyAiAllowance(env) {
  const store = env.MATCH_SIGNAL_ANALYST_STORE;
  const day = new Date().toISOString().slice(0, 10), key = "ai-analyst-usage:" + day;
  const used = Number(await store.get(key) || 0);
  if (!Number.isFinite(used) || used >= AI_DAILY_LIMIT) return { allowed: false, used: Number.isFinite(used) ? used : AI_DAILY_LIMIT, limit: AI_DAILY_LIMIT };
  await store.put(key, String(used + 1), { expirationTtl: 259200 });
  return { allowed: true, used: used + 1, limit: AI_DAILY_LIMIT };
}

export async function callAnalystModel(env, systemPrompt, userPrompt, maxTokens = 900) {
  if (!env.AI || typeof env.AI.run !== "function") throw new Error("AI_BINDING_NOT_CONFIGURED");
  const model = typeof env.ANALYST_AI_MODEL === "string" && env.ANALYST_AI_MODEL.trim() ? env.ANALYST_AI_MODEL.trim() : DEFAULT_AI_MODEL;
  const raw = await env.AI.run(model, {
    messages: [{ role: "system", content: systemPrompt }, { role: "user", content: userPrompt }],
    max_tokens: maxTokens, temperature: 0.1
  });
  let answer = raw && typeof raw.response === "string" ? raw.response : null;
  if (!answer && raw && raw.result && typeof raw.result.response === "string") answer = raw.result.response;
  if (!answer && raw && raw.choices && raw.choices[0] && raw.choices[0].message) answer = raw.choices[0].message.content;
  if (typeof answer !== "string" || !answer.trim()) throw new Error("AI_EMPTY_RESPONSE");
  return { answer: answer.trim(), model: model };
}

function sanitizeBuilder(builder) {
  if (!builder || typeof builder !== "object" || builder.unavailable) return { unavailable: true };
  const batches = Array.isArray(builder.batches) ? builder.batches.slice(0, 6) : [];
  return {
    generated_at: builder.generated_at || null, engine_version: builder.engine_version || null,
    mode: builder.mode || null, status: builder.status || null,
    batch_count: builder.batch_count == null ? batches.length : builder.batch_count,
    candidate_diagnostics: builder.candidate_diagnostics || null,
    selection_policy: {
      minimum_combined_odds: builder.selection_policy && builder.selection_policy.minimum_combined_odds != null ? builder.selection_policy.minimum_combined_odds : builder.batch_policy && builder.batch_policy.min_combined_odds,
      target_combined_odds: builder.selection_policy && builder.selection_policy.target_combined_odds != null ? builder.selection_policy.target_combined_odds : builder.batch_policy && builder.batch_policy.target_combined_odds,
      max_legs: builder.selection_policy && builder.selection_policy.max_legs != null ? builder.selection_policy.max_legs : builder.batch_policy && builder.batch_policy.max_legs,
      never_force_accumulator: builder.selection_policy && builder.selection_policy.never_force_accumulator,
      real_money_execution: false
    },
    batches: batches.map(function(batch) {
      return {
        batch_id: batch.batch_id || null, leg_count: batch.leg_count == null ? (batch.legs || []).length : batch.leg_count,
        combined_odds: batch.combined_odds == null ? null : batch.combined_odds,
        combined_model_rating: batch.combined_model_rating == null ? null : batch.combined_model_rating,
        combined_model_probability: batch.combined_model_probability == null ? null : batch.combined_model_probability,
        primary_lane: batch.primary_lane || null,
        legs: (batch.legs || []).slice(0, 7).map(function(leg) {
          return {
            product: leg.product || leg.sport || null, competition: leg.competition || null,
            match: leg.match || null, pick: leg.pick || leg.builder_pick || null,
            line: leg.line == null ? null : leg.line,
            odds: leg.bookmaker_odds == null ? (leg.odds == null ? null : leg.odds) : leg.bookmaker_odds,
            model_probability: leg.model_probability == null ? null : leg.model_probability,
            de_vig_probability: leg.de_vig_probability == null ? null : leg.de_vig_probability,
            market_odds_age_seconds: leg.market_odds_age_seconds == null ? null : leg.market_odds_age_seconds,
            qualification_lane: leg.qualification_lane || null, status: leg.status || null
          };
        })
      };
    })
  };
}

async function readArtifact(request, path) {
  const url = new URL(path, request.url);
  try {
    const response = await fetch(url.toString(), { headers: { Accept: "application/json" }, cf: { cacheTtl: 0, cacheEverything: false } });
    if (!response.ok) return { unavailable: true, http_status: response.status };
    const value = await response.json();
    return value && typeof value === "object" ? value : { unavailable: true };
  } catch { return { unavailable: true }; }
}

export async function collectPublicDiagnostics(request) {
  const paths = ["/data/system_health.json", "/data/pipeline_status.json", "/data/automation_health.json", "/data/results_first_evidence_report.json", "/data/odds_builder.json"];
  const values = await Promise.all(paths.map(function(path) { return readArtifact(request, path); }));
  const health = values[0], pipeline = values[1], automation = values[2], report = values[3], builder = values[4];
  return {
    collected_at: new Date().toISOString(),
    system_health: health.unavailable ? health : {
      generated_at: health.generated_at || null, status: health.status || "unknown",
      critical_issues: health.critical_issues == null ? null : health.critical_issues,
      warning_issues: health.warning_issues == null ? null : health.warning_issues,
      info_issues: health.info_issues == null ? null : health.info_issues,
      issues: (health.issues || []).slice(0, 12),
      checks: (health.checks || []).slice(0, 12).map(function(item) {
        return { engine: item.engine, status: item.status, age_hours: item.age_hours == null ? null : item.age_hours, threshold_hours: item.threshold_hours == null ? null : item.threshold_hours };
      })
    },
    core_pipeline: pipeline.unavailable ? pipeline : {
      updated_at: pipeline.updated_at || null, prediction_count: pipeline.prediction_count == null ? null : pipeline.prediction_count,
      football_count: pipeline.football_count == null ? null : pipeline.football_count, tennis_count: pipeline.tennis_count == null ? null : pipeline.tennis_count,
      errors: (pipeline.errors || []).slice(0, 8), quality_control: pipeline.quality_control || null,
      market_data: pipeline.market_data ? {
        provider: pipeline.market_data.provider || null, fetched_at: pipeline.market_data.fetched_at || null,
        football_events: pipeline.market_data.football_events == null ? null : pipeline.market_data.football_events,
        tennis_events: pipeline.market_data.tennis_events == null ? null : pipeline.market_data.tennis_events,
        matched: pipeline.market_data.matched == null ? null : pipeline.market_data.matched,
        unmatched: pipeline.market_data.unmatched == null ? null : pipeline.market_data.unmatched,
        coverage: pipeline.market_data.coverage == null ? null : pipeline.market_data.coverage,
        fetch_errors: (pipeline.market_data.fetch_errors || []).slice(0, 6)
      } : null
    },
    automation: automation.unavailable ? automation : {
      updated_at: automation.updated_at || null, automation_status: automation.automation_status || null,
      pipeline_age_hours: automation.pipeline_age_hours == null ? null : automation.pipeline_age_hours,
      odds_builder_age_hours: automation.odds_builder_age_hours == null ? null : automation.odds_builder_age_hours,
      expansion_age_hours: automation.expansion_age_hours == null ? null : automation.expansion_age_hours,
      virtual_lab_age_hours: automation.virtual_lab_age_hours == null ? null : automation.virtual_lab_age_hours,
      virtual_lab_status_age_hours: automation.virtual_lab_status_age_hours == null ? null : automation.virtual_lab_status_age_hours,
      thresholds: automation.thresholds || null, actions: (automation.actions || []).slice(0, 8)
    },
    results_first_report: report.unavailable ? report : {
      generated_at: report.generated_at || null, mode: report.mode || null,
      diagnostic_only: report.diagnostic_only == null ? null : report.diagnostic_only,
      tracker_summary: report.tracker_summary || null,
      exact_line_side_records: (report.exact_line_side_records || []).slice(0, 20),
      ticket_shape_records: (report.ticket_shape_records || []).slice(0, 10),
      product_records: (report.product_records || []).slice(0, 10)
    },
    odds_builder: sanitizeBuilder(builder)
  };
}

export function extractJsonObject(text) {
  if (typeof text !== "string") return null;
  const cleaned = text.trim().replace(/^json\s*/i, "");
  try {
    const direct = JSON.parse(cleaned);
    if (direct && typeof direct === "object" && !Array.isArray(direct)) return direct;
  } catch {}
  const first = cleaned.indexOf("{"), last = cleaned.lastIndexOf("}");
  if (first < 0 || last <= first) return null;
  try {
    const parsed = JSON.parse(cleaned.slice(first, last + 1));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
}
