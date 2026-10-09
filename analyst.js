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
      setMessage("chatStatus", "Request " + result.usage.daily_requests_used + " of " + result.usage.daily_request_limit + " used today.");
    } catch (error) {
      answerNode.textContent = error.message + (error.status === 503 ? "\n\nConfigure Workers AI and the private KV/token bindings in Cloudflare, then redeploy." : "");
      setMessage("chatStatus", error.status === 429 ? "Daily AI request limit reached." : "Request failed; no ticket records were changed.", "small error");
    } finally { $("sendButton").disabled = false; }
  }
  async function parseReceipt() {
    const receiptText = $("receiptText").value.trim();
    if (receiptText.length < 20) { setMessage("parseStatus", "Paste the copied ticket text first.", "small error"); return; }
    $("parseButton").disabled = true;
    setMessage("parseStatus", "Parsing for review. This does not save anything.");
    try {
      const result = await api("./api/analyst/parse-ticket", { method: "POST", body: { receipt_text: receiptText } });
      $("ticketDraft").value = JSON.stringify(result.ticket, null, 2);
      $("draftSection").classList.remove("hidden");
      const warnings = result.validation_errors || [];
      setMessage("draftStatus", warnings.length
        ? "Review required: " + warnings.join("; ") + ". Edit the JSON until valid, then save."
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
