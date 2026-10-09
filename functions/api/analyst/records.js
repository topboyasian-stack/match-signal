import {
  authorizeAnalystRequest,
  emptyReviewDocument,
  jsonResponse,
  loadPrivateDocument,
  readJsonBody,
  REVIEW_KEY,
  MAX_REVIEW_BYTES,
  summarizeReviewDocument,
  validateReviewDocument
} from "../../_shared/analyst.mjs";

export async function onRequestGet(context) {
  const access = await authorizeAnalystRequest(context);
  if (access.response) return access.response;
  try {
    const document = await loadPrivateDocument(context.env);
    return jsonResponse({ document: document, summary: summarizeReviewDocument(document) });
  } catch (error) {
    const reason = error && error.message === "PRIVATE_RECORDS_INVALID_JSON" ? "invalid_json" : "validation_failed";
    return jsonResponse({ error: "PRIVATE_RECORDS_UNAVAILABLE", reason: reason }, 500);
  }
}

export async function onRequestPut(context) {
  const access = await authorizeAnalystRequest(context);
  if (access.response) return access.response;
  const parsed = await readJsonBody(context.request, MAX_REVIEW_BYTES);
  if (parsed.error) return jsonResponse({ error: parsed.error }, parsed.error === "REQUEST_TOO_LARGE" ? 413 : 400);
  const errors = validateReviewDocument(parsed.body);
  if (errors.length) return jsonResponse({ error: "INVALID_REVIEW_DOCUMENT", validation_errors: errors.slice(0, 40) }, 400);
  const expectedRevision = context.request.headers.get("If-Match");
  if (!expectedRevision) return jsonResponse({ error: "PRECONDITION_REQUIRED", message: "Reload the private ledger before replacing it." }, 428);
  let current;
  try { current = await loadPrivateDocument(context.env); }
  catch { return jsonResponse({ error: "PRIVATE_RECORDS_UNAVAILABLE" }, 500); }
  if (expectedRevision !== current.updated_at) {
    return jsonResponse({ error: "LEDGER_REVISION_CONFLICT", message: "The private ledger changed in another tab. Reload it and retry to avoid overwriting saved records." }, 409);
  }
  const document = Object.assign({}, parsed.body, { updated_at: new Date().toISOString() });
  try {
    await context.env.MATCH_SIGNAL_ANALYST_STORE.put(REVIEW_KEY, JSON.stringify(document));
    return jsonResponse({ status: "SAVED", summary: summarizeReviewDocument(document) });
  } catch {
    return jsonResponse({ error: "PRIVATE_RECORDS_SAVE_FAILED" }, 500);
  }
}

export async function onRequestDelete(context) {
  const access = await authorizeAnalystRequest(context);
  if (access.response) return access.response;
  try {
    await context.env.MATCH_SIGNAL_ANALYST_STORE.delete(REVIEW_KEY);
    const empty = emptyReviewDocument();
    return jsonResponse({ status: "DELETED", summary: summarizeReviewDocument(empty) });
  } catch {
    return jsonResponse({ error: "PRIVATE_RECORDS_DELETE_FAILED" }, 500);
  }
}
