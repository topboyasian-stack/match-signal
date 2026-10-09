(function () {
  "use strict";
  const $ = function(id) { return document.getElementById(id); };
  let accessToken = "";
  let currentDocument = null;

  function setMessage(id, message, className) {
    const node = $(id);
    node.textContent = message || "";
    node.className = className || "small";
  }
  function setConnected(connected) {
    $("workspace").classList.toggle("hidden", !connected);
    $("connectionStatus").textContent = connected ? "Connected · private mode" : "Not connected";
    $("connectionStatus").className = "status" + (connected ? " success" : "");
    $("disconnectButton").disabled = !connected;
  }
  async function api(path, options) {
    if (!accessToken) throw new Error("Connect with your analyst token first.");
    const opts = Object.assign({}, options || {});
    opts.headers = Object.assign({}, opts.headers || {}, { "Authorization": "Bearer " + accessToken });
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const response = await fetch(path, opts);
    const payload = await response.json().catch(function() { return {}; });
    if (!response.ok) {
      const error = new Error(payload.message || payload.error || ("HTTP " + response.status));
      error.status = response.status;
      throw error;
    }
    return payload;
  }
  function appendMessage(kind, text) {
    const row = document.createElement("div");
    row.className = "message " + kind;
    row.textContent = text;
    $("messages").appendChild(row);
    $("messages").scrollTop = $("messages").scrollHeight;
    return row;
  }
  function updateLedger(summary) {
    const count = summary || {};
    $("ledgerCounts").replaceChildren();
    const items = [
      ["Tickets", count.ticket_count || 0], ["Legs", count.leg_count || 0],
      ["Scored", count.scored_leg_count || 0], ["Won", count.actual_selection_outcomes && count.actual_selection_outcomes.WON || 0],
      ["Lost", count.actual_selection_outcomes && count.actual_selection_outcomes.LOST || 0],
      ["Unsettled", count.actual_selection_outcomes && count.actual_selection_outcomes.UNSETTLED_OR_MISSING_SCORE || 0]
    ];
    items.forEach(function(item) {
      const block = document.createElement("div");
      block.className = "count";
      const strong = document.createElement("strong");
      strong.textContent = String(item[1]);
      const caption = document.createElement("span");
      caption.textContent = item[0];
      block.append(strong, caption);
      $("ledgerCounts").appendChild(block);
    });
    const hit = count.actual_leg_hit_rate_excluding_pushes;
    $("ledgerStatus").textContent = count.ticket_count
      ? "Private ledger loaded · actual-leg hit rate excluding pushes: " + (hit == null ? "not yet available" : (Number(hit) * 100).toFixed(1) + "%") + ". Selected-ticket evidence is not an unbiased model backtest."
      : "Private ledger is empty. Parsed tickets remain drafts until you choose to save them.";
  }
  async function refreshLedger() {
    const payload = await api("./api/analyst/records");
    currentDocument = payload.document;
    updateLedger(payload.summary);
  }
  async function connect() {
    accessToken = $("accessToken").value.trim() || sessionStorage.getItem("matchSignalAnalystToken") || "";
    if (!accessToken) { setMessage("connectionMessage", "Paste the token configured in Cloudflare.", "small error"); return; }
    sessionStorage.setItem("matchSignalAnalystToken", accessToken);
    $("connectButton").disabled = true;
    setMessage("connectionMessage", "Connecting to private storage…");
    try {
      await refreshLedger();
      setConnected(true);
      setMessage("connectionMessage", "Connected. Private records are stored behind token-protected API routes.", "small success");
    } catch (error) {
      accessToken = "";
      sessionStorage.removeItem("matchSignalAnalystToken");
      setConnected(false);
      const message = error.status === 401 ? "Access denied. Check the token." :
        error.status === 503 ? "Cloudflare setup is incomplete: " + error.message : "Could not connect: " + error.message;
      setMessage("connectionMessage", message, "small error");
    } finally { $("connectButton").disabled = false; }
  }
  function disconnect() {
    accessToken = "";
    currentDocument = null;
    sessionStorage.removeItem("matchSignalAnalystToken");
    $("accessToken").value = "";
    $("draftSection").classList.add("hidden");
    setConnected(false);
    setMessage("connectionMessage", "Disconnected. Private records remain in the protected store until you delete them.", "small");
  }
  function formatVerifiedFacts(f) {
    if (!f || typeof f !== "object") return "";
    const n = function(v) { return v == null || !Number.isFinite(Number(v)) ? "unavailable" : Number(v).toLocaleString(); };
    const age = function(k) {
      const a = f.artifacts && f.artifacts[k];
      if (!a || a.age_minutes == null) return "age unavailable";
      const v = Number(a.age_minutes);
      const text = v >= 120 ? (v / 60).toFixed(2) + "h old" : Math.round(v) + "m old";
      return text + (a.threshold_hours == null ? "" : " (" + String(a.status).toLowerCase().replace(/_/g, " ") + ", " + a.threshold_hours + "h threshold)");
    };
    const h = f.system_health || {}, p = f.pipeline || {}, m = p.market_matching || {}, t = f.builder_ticket_results || {};
    const tf = f.tennis_forward_discovery || {}, desk = f.prediction_desk || {};
    const rc = h.reported_issue_counts || {};
    const lines = [
      "VERIFIED SOURCE FACTS · calculated from records, not AI prose",
      "Collected: " + String(f.collected_at || "timestamp unavailable"),
      "Health: " + String(h.status || "unknown") + "; critical " + n(rc.critical) + ", warning " + n(rc.warning) + ", info " + n(rc.info) + "; count check " + String(h.issue_count_check || "unavailable") + ".",
      "Pipeline: " + age("core_pipeline") + "; " + n(p.prediction_count) + " predictions (" + n(p.football_count) + " football, " + n(p.tennis_count) + " tennis); " + n(p.error_count) + " errors.",
      "Automation artifact: " + age("automation") + "."
    ];
    const issues = Array.isArray(h.issues) ? h.issues : [];
    if (issues.length) lines.push("Health issues: " + issues.map(function(x) {
      return String(x.severity || "unknown").toUpperCase() + " " + String(x.code || "unnamed") + " — " + String(x.detail || "No detail supplied");
    }).join("; ") + ".");
    const tours = tf.tours || {};
    const tennisParts = Object.keys(tours).map(function(tour) {
      const x = tours[tour] || {};
      const rejected = x.rejected && typeof x.rejected === "object"
        ? Object.keys(x.rejected).map(function(k) { return k + ": " + n(x.rejected[k]); }).join(", ")
        : "none recorded";
      return tour + ": " + n(x.events_seen) + " events seen, " + n(x.valid_singles) + " valid singles, " +
        n(x.new_predictions) + " new predictions; rejected " + rejected +
        (x.error ? "; error " + String(x.error) : "");
    });
    lines.push("Tennis forward discovery: " + age("tennis_forward_discovery") +
      "; window " + n(tf.window_days) + " days; " + (tennisParts.join(" | ") || "tour details unavailable") + ".");
    const deskFilters = desk.publication_filters || {};
    lines.push("Prediction Desk: " + age("prediction_desk") + "; status " + String(desk.status || "unavailable") + "; " + n(desk.event_count) +
      " published events; " + n(desk.live_count) + " live; " + n(desk.pending_settlement_count) +
      " pending settlement. Hidden past-kickoff rows " + n(deskFilters.past_kickoff_rows_hidden) +
      "; stale live flags removed " + n(deskFilters.stale_live_flags_hidden) +
      "; expired settlement rows hidden " + n(deskFilters.expired_settled_rows_hidden) +
      ". Hiding a row does not delete its archive history.");
    const highUnder = Array.isArray(desk.high_line_under_evidence) ? desk.high_line_under_evidence : [];
    if (highUnder.length) lines.push("High-line Under exact-line evidence: " + highUnder.map(function(x) {
      const product = String(x.product || "virtual").toLowerCase();
      const sample = n(x.walkforward_n);
      const hit = x.walkforward_hit_rate == null ? "hit rate unavailable" : (100 * Number(x.walkforward_hit_rate)).toFixed(1) + "%";
      const line = x.line == null ? "?" : String(x.line);
      const status = String(x.qualification_status || "NOT_QUALIFIED");
      const groupQualification = x.betting_qualified
        ? "at least one event in this grouped product/line/side is marked paper-qualified"
        : "no event in this grouped product/line/side is marked paper-qualified";
      const isVFootballHighUnder = product === "vfootball" && String(x.side || "under").toLowerCase() === "under" && Number(x.line) >= 7.5;
      let assessment;
      if (isVFootballHighUnder) {
        const enough = Number(x.walkforward_n || 0) >= 30 && x.walkforward_hit_rate != null && Number(x.walkforward_hit_rate) >= 0.65;
        assessment = enough
          ? "VFootball-specific 30-row/65% evidence threshold met; current-market and Builder gates still apply"
          : "VFootball-specific 30-row/65% gate PENDING; this product/line/side must remain unqualified";
        if (!enough && x.betting_qualified) {
          assessment += "; WARNING: grouped qualification conflicts with this gate and needs event-level inspection";
        }
      } else {
        assessment = "VFootball-specific 30-row/65% gate does not apply to this product; use its source qualification and product-specific gates";
      }
      return product + " U" + line + ": " + sample + " exact-line walk-forward rows, " + hit +
        "; source status " + status + "; " + groupQualification + "; " + assessment;
    }).join("; ") + ".");
    if (m.coverage_denominator != null && m.calculated_coverage != null) lines.push(
      "Market matching: " + n(m.matching_records) + "/" + n(m.coverage_denominator) + " matchable records = " + (100 * Number(m.calculated_coverage)).toFixed(2) + "%; provider event counts are a separate measure."
    );
    if (t.tracked_tickets != null) {
      const hit = t.ticket_accuracy_excluding_pending == null ? "unavailable" : (100 * Number(t.ticket_accuracy_excluding_pending)).toFixed(2) + "%";
      lines.push("Builder report: " + age("results_first_report") + "; " + n(t.tracked_tickets) + " tracked, " + n(t.pending_tickets) + " pending, " + n(t.won_tickets) + " won, " + n(t.lost_tickets) + " lost; " + n(t.settled_tickets) + " settled; ticket accuracy " + hit + ".");
      const shapes = Array.isArray(t.ticket_shape_records) ? t.ticket_shape_records : [];
      if (shapes.length) lines.push("Settled ticket shapes: " + shapes.map(function(x) {
        return String(x.ticket_shape || "shape").replace(/^ou_legs_/, "") + "-leg " + n(x.wins) + "/" + n(Number(x.wins || 0) + Number(x.losses || 0)) + " wins (" + (x.accuracy == null ? "rate unavailable" : (100 * Number(x.accuracy)).toFixed(2) + "%") + ")";
      }).join("; ") + ".");
    }
    const l = t.individual_leg_statuses_across_tracker || {};
    if (l.settled_individual_legs != null && t.settled_ou_legs_within_fully_settled_tickets != null && Number(l.settled_individual_legs) !== Number(t.settled_ou_legs_within_fully_settled_tickets)) {
      lines.push("Cohort note: tracker-wide leg statuses can include legs from still-pending tickets; do not combine that denominator with legs from fully settled tickets.");
    }
    const b = f.odds_builder || {};
    lines.push("Odds Builder: " + age("odds_builder") + "; status " + String(b.status || "unavailable") +
      "; evaluated " + n(b.evaluated_candidates) + ", LIVE_VALUE category " + n(b.live_value_candidates) +
      ", REJECTED category " + n(b.rejected_candidates) + ".");
    if (Array.isArray(f.flags) && f.flags.length) lines.push("Flags: " + f.flags.join(" "));
    if (h.issue_count_check === "MISMATCH") lines.push("The health artifact's issue counts do not match the severities counted in its issue records.");
    return lines.join("\n");
  }

  async function askQuestion(question) {
    const cleaned = String(question || $("question").value || "").trim();
    if (!cleaned) return;
    $("question").value = "";
    appendMessage("user", cleaned);
    const answerNode = appendMessage("assistant", "Checking timestamped evidence…");
    $("sendButton").disabled = true;
    setMessage("chatStatus", "One on-demand AI request; no background loop.");
    try {
      const result = await api("./api/analyst/chat", { method: "POST", body: { question: cleaned } });
      answerNode.textContent = result.answer || "No answer returned.";
      const stamps = result.evidence_timestamps || {};
      const lines = [
        stamps.system_health ? "health " + stamps.system_health : null,
        stamps.core_pipeline ? "pipeline " + stamps.core_pipeline : null,
        stamps.results_first_report ? "ticket report " + stamps.results_first_report : null
      ].filter(Boolean);
      if (lines.length) appendMessage("system", "Evidence timestamps: " + lines.join(" · "));
      const factsText = formatVerifiedFacts(result.verified_facts);
      if (factsText) appendMessage("system", factsText);
      setMessage("chatStatus", "Request " + result.usage.daily_requests_used + " of " + result.usage.daily_request_limit + " used today.");
    } catch (error) {
      answerNode.textContent = error.message + (error.status === 503 ? "\n\nConfigure Workers AI and the private KV/token bindings in Cloudflare, then redeploy." : "");
      setMessage("chatStatus", error.status === 429 ? "Daily AI request limit reached." : "Request failed; no ticket records were changed.", "small error");
    } finally { $("sendButton").disabled = false; }
  }
  function toLocalDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return shifted.toISOString().slice(0, 16);
  }
  function addDeskField(parent, labelText, type, value, options) {
    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = type === "select" ? document.createElement("select") : document.createElement("input");
    if (type !== "select") input.type = type;
    if (type === "select") {
      [["over", "Over"], ["under", "Under"]].forEach(function(item) {
        const option = document.createElement("option");
        option.value = item[0];
        option.textContent = item[1];
        input.appendChild(option);
      });
    }
    input.value = value == null ? "" : String(value);
    if (options) Object.keys(options).forEach(function(key) { input.setAttribute(key, options[key]); });
    const id = "deskField_" + Math.random().toString(36).slice(2, 10);
    input.id = id;
    label.htmlFor = id;
    field.append(label, input);
    parent.appendChild(field);
    return input;
  }
  function renderDeskFields(ticket) {
    const root = $("draftFields");
    root.replaceChildren();
    (ticket.legs || []).forEach(function(leg, index) {
      const snapshot = leg.desk_snapshot || {};
      const card = document.createElement("div");
      card.className = "leg-editor";
      card.setAttribute("data-leg-index", String(index));
      const title = document.createElement("div");
      title.className = "leg-editor-title";
      title.textContent = "Leg " + (index + 1) + " · " + String(leg.match || "Match to verify");
      const sub = document.createElement("p");
      sub.className = "small";
      sub.textContent = "Actual slip pick: " + String(leg.actual_selection && leg.actual_selection.pick || "unknown").toUpperCase() +
        " " + String(leg.actual_selection && leg.actual_selection.line != null ? leg.actual_selection.line : "line missing") +
        " @ " + String(leg.actual_selection && leg.actual_selection.odds != null ? leg.actual_selection.odds : "odds missing");
      const fields = document.createElement("div");
      fields.className = "desk-grid";
      addDeskField(fields, "Desk side", "select", snapshot.pick || "over");
      addDeskField(fields, "Desk goal line", "number", snapshot.line, { min: "0", step: "0.5", placeholder: "e.g. 2.5" });
      addDeskField(fields, "Desk odds (optional)", "number", snapshot.odds, { min: "1.001", step: "0.01", placeholder: "e.g. 1.70" });
      addDeskField(fields, "Desk model probability (optional)", "number", snapshot.model_probability, { min: "0", max: "1", step: "0.001", placeholder: "e.g. 0.83" });
      addDeskField(fields, "Kickoff time (if known)", "datetime-local", toLocalDateTime(leg.kickoff_at), {});
      addDeskField(fields, "When you saw this desk pick", "datetime-local", toLocalDateTime(snapshot.captured_at), {});
      card.append(title, sub, fields);
      root.appendChild(card);
    });
  }
  function applyDeskFields(ticket) {
    const cards = $("draftFields").querySelectorAll("[data-leg-index]");
    cards.forEach(function(card) {
      const fields = card.querySelectorAll("input,select");
      const pick = fields[0] ? fields[0].value : "";
      const lineText = fields[1] ? fields[1].value.trim() : "";
      const oddsText = fields[2] ? fields[2].value.trim() : "";
      const probabilityText = fields[3] ? fields[3].value.trim() : "";
      const kickoffText = fields[4] ? fields[4].value : "";
      const capturedText = fields[5] ? fields[5].value : "";
      const index = Number(card.getAttribute("data-leg-index"));
      const leg = ticket.legs[index];
      if (!leg) return;
      if (kickoffText) leg.kickoff_at = new Date(kickoffText).toISOString();
      else delete leg.kickoff_at;
      if (!lineText) {
        delete leg.desk_snapshot;
        return;
      }
      if (!capturedText) throw new Error("Leg " + (index + 1) + ": enter when you saw the original desk pick, or leave its desk line blank.");
      const line = Number(lineText);
      if (!Number.isFinite(line) || line < 0) throw new Error("Leg " + (index + 1) + ": the desk line is invalid.");
      const snapshot = { market: "total_goals_over_under", pick: pick, line: line, captured_at: new Date(capturedText).toISOString(), provenance: "user_reported" };
      if (oddsText) {
        const odds = Number(oddsText);
        if (!Number.isFinite(odds) || odds <= 1) throw new Error("Leg " + (index + 1) + ": desk odds must be greater than 1.");
        snapshot.odds = odds;
      }
      if (probabilityText) {
        const probability = Number(probabilityText);
        if (!Number.isFinite(probability) || probability < 0 || probability > 1) throw new Error("Leg " + (index + 1) + ": desk model probability must be from 0 to 1.");
        snapshot.model_probability = probability;
      }
      leg.desk_snapshot = snapshot;
    });
    $("ticketDraft").value = JSON.stringify(ticket, null, 2);
    return ticket;
  }

  async function parseReceipt() {
    const receiptText = $("receiptText").value.trim();
    if (receiptText.length < 20) { setMessage("parseStatus", "Paste the copied ticket text first.", "small error"); return; }
    $("parseButton").disabled = true;
    setMessage("parseStatus", "Parsing for review. This does not save anything.");
    try {
      const result = await api("./api/analyst/parse-ticket", { method: "POST", body: { receipt_text: receiptText } });
      $("ticketDraft").value = JSON.stringify(result.ticket, null, 2);
      renderDeskFields(result.ticket);
      $("draftSection").classList.remove("hidden");
      const warnings = result.validation_errors || [];
      setMessage("draftStatus", warnings.length
        ? "Review required: " + warnings.join("; ") + ". Correct the review fields or advanced JSON before saving."
        : "Draft extracted. Verify every leg, exact line, odds, score and reported result. No desk data will be guessed.", warnings.length ? "small error" : "small");
      setMessage("parseStatus", "Draft ready. Nothing has been saved.");
    } catch (error) {
      setMessage("parseStatus", error.message + (error.status === 503 ? " Workers AI may not be configured." : ""), "small error");
    } finally { $("parseButton").disabled = false; }
  }
  async function saveDraft() {
    if (!currentDocument) throw new Error("Connect and load the ledger first.");
    let ticket;
    try { ticket = JSON.parse($("ticketDraft").value); }
    catch { throw new Error("The draft is not valid JSON. Correct it before saving."); }
    if (!ticket || typeof ticket !== "object" || !Array.isArray(ticket.legs)) throw new Error("The draft must be a ticket object with a legs array.");
    ticket = applyDeskFields(ticket);
    if (currentDocument.tickets.some(function(existing) { return existing.ticket_ref === ticket.ticket_ref; })) {
      throw new Error("This ticket reference already exists. Discard and parse it again.");
    }
    const next = Object.assign({}, currentDocument, { updated_at: new Date().toISOString(), tickets: currentDocument.tickets.concat([ticket]) });
    await api("./api/analyst/records", { method: "PUT", headers: { "If-Match": currentDocument.updated_at }, body: next });
    await refreshLedger();
    $("draftSection").classList.add("hidden");
    $("receiptText").value = "";
    setMessage("parseStatus", "Ticket saved privately. It remains user-selected evidence and is not model-training input.", "small success");
  }
  function exportLedger() {
    if (!currentDocument) return;
    const blob = new Blob([JSON.stringify(currentDocument, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "match-signal-private-ticket-review.json";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }
  async function importLedger(file) {
    if (!file) return;
    const document = JSON.parse(await file.text());
    if (!document || document.record_type !== "private_user_ticket_review" || !Array.isArray(document.tickets)) throw new Error("Not a Match Signal private-ticket review document.");
    if (!confirm("Replace the saved private ledger with " + document.tickets.length + " ticket(s)? Export your current ledger first if you need a backup.")) return;
    await api("./api/analyst/records", { method: "PUT", headers: { "If-Match": currentDocument.updated_at }, body: document });
    await refreshLedger();
    setMessage("ledgerStatus", "Imported and saved privately.", "sub success");
  }
  async function deleteLedger() {
    if (!confirm("Permanently delete all saved private user-ticket evidence? This will not delete public model history or Builder records.")) return;
    await api("./api/analyst/records", { method: "DELETE" });
    await refreshLedger();
    setMessage("ledgerStatus", "Private user-ticket evidence deleted.", "sub success");
  }

  $("connectButton").addEventListener("click", connect);
  $("disconnectButton").addEventListener("click", disconnect);
  $("chatForm").addEventListener("submit", function(event) { event.preventDefault(); askQuestion(); });
  $("parseButton").addEventListener("click", function() { parseReceipt().catch(function(error) { setMessage("parseStatus", error.message, "small error"); }); });
  $("saveDraftButton").addEventListener("click", function() { saveDraft().catch(function(error) { setMessage("draftStatus", error.message, "small error"); }); });
  $("cancelDraftButton").addEventListener("click", function() { $("draftSection").classList.add("hidden"); });
  $("exportButton").addEventListener("click", exportLedger);
  $("deleteButton").addEventListener("click", function() { deleteLedger().catch(function(error) { setMessage("ledgerStatus", error.message, "sub error"); }); });
  $("importFile").addEventListener("change", function(event) {
    importLedger(event.target.files && event.target.files[0]).catch(function(error) { setMessage("ledgerStatus", error.message, "sub error"); }).finally(function() { event.target.value = ""; });
  });
  document.querySelectorAll("[data-question]").forEach(function(button) {
    button.addEventListener("click", function() { askQuestion(button.getAttribute("data-question")); });
  });
  $("disconnectButton").disabled = true;
  setConnected(false);
  const stored = sessionStorage.getItem("matchSignalAnalystToken");
  if (stored) { $("accessToken").value = stored; accessToken = stored; connect(); }
})();
