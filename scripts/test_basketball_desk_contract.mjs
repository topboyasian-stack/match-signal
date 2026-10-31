import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const root = new URL("../", import.meta.url);
const read = p => readFile(new URL(p, root), "utf8");
const [html, css, ui, api, workflow, booking, recorder, nbaRecorderWorkflow] = await Promise.all([
  read("basketball.html"), read("basketball-design.css"), read("basketball-live.js"),
  read("functions/api/sportybet-basketball.js"), read(".github/workflows/cloudflare-pages.yml"), read("functions/api/sportybet-basketball-booking.js"), read("scripts/record_nba_live_behavior.py"), read(".github/workflows/nba-live-observation.yml")
]);
assert.ok(html.includes("MS-BASKETBALL-DESK-2026.10.24-V11"), "Basketball must publish the new design marker");
assert.ok(html.includes("core-workspaces-design.css?v=20261014-full-v1"), "Basketball must use the shared Match Signal design layer");
assert.ok(html.includes("basketball-live.js?v=20261031-upcoming-kickoff-v9"), "Basketball must cache-bust the visible booking error/retry logic");
assert.ok(html.includes("basketball-design.css?v=20261024-builder-dark-v3"), "Basketball must load its latest contrast-corrected scoped design layer");
assert.ok(workflow.includes("MS-BASKETBALL-DESK-2026.10.24-V11") && workflow.includes("basketball-design.css?v=20261024-builder-dark-v3"), "Pages production smoke markers must match the current Basketball page and CSS versions");
assert.ok(html.includes('id="msNav"') && html.includes('workspace-ui.js?v=20261023-basketball-nav1'), "Basketball must use the single shared site navigation");
for (const id of ["liveGames","upcomingGames","totalsBoard","finalResults","nbaTotalsLedger","performance","marketStatus","totalsStatus"]) assert.ok(html.includes('id="'+id+'"'), "Basketball must preserve renderer mount "+id);
assert.ok(css.includes("MATCH-SIGNAL-BASKETBALL-DESK-V1"), "Basketball scoped design marker missing");
assert.ok(css.includes("MATCH-SIGNAL-BASKETBALL-DARK-V3") && html.includes("basketball-design.css?v=20261024-builder-dark-v3"), "Basketball must deploy the cache-busted contrast/readability safety net");
assert.ok(css.includes("MATCH-SIGNAL-BASKETBALL-BUILDER-DARK-V1") && css.includes(".nba-builder-card") && css.includes("background:linear-gradient(145deg,#132231,#0e1822)"), "All four basketball builders must use the dark terminal theme");
assert.ok(css.includes("@media(max-width:480px)") && css.includes("@media(prefers-reduced-motion:reduce)") && css.includes(":focus-visible"), "Basketball design must remain responsive and accessible");
assert.ok(ui.includes("S.predictions.filter(function(p){return new Date(p.start_time).getTime()>now;})"), "Upcoming NBA totals must exclude fixtures whose scheduled start has passed");
assert.ok(ui.includes("return !(e&&(e.completed||e.live))&&new Date(p.start_time).getTime()>now;"), "Upcoming NBA predictions must exclude every fixture after scheduled kickoff even when the score feed has no matching live row");
assert.ok(ui.includes("function bestSportyBetTotalMarket(markets)") && ui.includes("String(m.id)") && ui.includes("225"), "Totals must select the explicit SportyBet market ID for full-game O/U including overtime");
assert.ok(ui.includes("function sportyBetTotalMarkets(markets)") && ui.includes("data-total-line-choice") && ui.includes("SELECTED_TOTAL_LINES"), "Basketball totals must expose live-feed alternative lines and use the selected line for the card and builder");
assert.ok(ui.includes("length>8") && ui.includes("length>=8") && ui.includes("not verified by SportyBet"), "Basketball builders must enforce the eight-leg limit and withhold unverified combined odds");
assert.ok(ui.includes("Math.abs(a-b)<=45*60*1000"), "SportyBet quotes must match exact teams and near-identical kickoff times");
assert.ok(ui.includes("replace(/\\s+/g,' ')"), "NBA team-name normalization must collapse whitespace rather than match a literal backslash-s sequence");
assert.ok(ui.includes("Date.now()-fetched<=15*60*1000") && ui.includes("fresh:Number.isFinite(fetched)"), "Stale SportyBet quotes must be withheld while fresh quotes remain eligible");
assert.ok(ui.includes("Historical line is context only; no current lean or odds value is inferred.") && ui.includes("Current exact SportyBet event · full-game total market 225"), "Totals must withhold stale prices and clearly label only exact current SportyBet quotes");
assert.ok(ui.includes("edge=fresh&&modelFresh&&Number.isFinite(expected)&&line!=null?expected-line:null") && ui.includes("historical line not used for lean"), "Historical lines must never produce a current model lean or edge");
assert.ok(ui.includes("modelFresh=Number.isFinite(modelGenerated)&&now-modelGenerated<=24*60*60*1000") && ui.includes("edge=fresh&&modelFresh&&Number.isFinite(expected)&&line!=null?expected-line:null") && ui.includes("stale projection · refresh required"), "Stale NBA projections must not produce current leans even when the bookmaker quote is fresh");
assert.ok(api.includes("sportId:'sr:sport:2'"), "SportyBet basketball feed must request the basketball sport ID");
assert.ok(api.includes("https://www.sportybet.com"), "SportyBet feed must fall back to the direct Nigeria endpoint if the proxy rejects basketball");
assert.ok(api.includes("const STANDARD_MARKET_IDS='1,18,10,29,11,26,36,14,60100,186,189,202,204,210'") && api.includes("marketId:'225'"), "Feed must request the provider's supported standard market list and probe O/U incl overtime separately");
assert.ok(api.includes("/api/ng/factsCenter/wapConfigurableUpcomingEvents"), "Feed must have a supported SportyBet upcoming-event fallback");
assert.ok(ui.includes("suspend|closed|inactive|settled|unavailable|stop"), "Suspended or closed SportyBet total markets must be withheld");
assert.ok(ui.includes("function bestSportyBetTotalMarket(markets)") && ui.includes("balance=Math.abs(Math.log") && ui.includes("status!=='0'"), "Totals must choose an active, balanced mainline instead of the first alternate line and reject non-open numeric statuses");
assert.ok(api.includes("total_including_overtime:'225'"), "API contract must explicitly identify total incl overtime");
assert.ok(workflow.includes("node scripts/test_basketball_desk_contract.mjs"), "Deployment must execute Basketball contract tests");

assert.ok(html.includes("How to read this — one clear decision") && html.includes("Model at least 3 points above line"), "Totals page must explain how to choose Over, Under or no clear lean");
assert.ok(html.includes('id="basketball-builders"') && html.includes('id="basketballBuilderWorkspace"'), "Basketball page must expose its four-builder workspace");
assert.ok(ui.includes("function totalsLedgerHtml()") && ui.includes("data/nba_totals_ledger.json") && ui.includes("totalSummary.accuracy"), "NBA totals must read persistent settlement records and calculate accuracy only from decided settlements");
assert.ok(html.includes("PERSISTENT SETTLEMENT LEDGER"), "Basketball desk must expose retained totals settlements");
assert.ok(ui.includes("function renderBuilders()") && ui.includes("BASKETBALL_BUILDERS=[[],[],[],[]]") && ui.includes("data-builder-generate"), "Four independent builder cards must be rendered");
assert.ok(ui.includes("BUILDER_ERRORS") && ui.includes("Code not generated") && ui.includes("data-builder-retry"), "Booking failures must remain visible in the relevant builder with a retry action");
assert.ok(ui.includes("Booking API returned non-JSON (HTTP ") && ui.includes("await response.text()"), "Browser must surface diagnostics if the booking API itself returns non-JSON");
assert.ok(booking.includes("hosts=['https://mobile.sportybet.com','https://lite.sportybet.com','https://www.sportybet.com']") && booking.includes("official web hosts") && booking.includes("content-type") && booking.includes("unavailable_count"), "Share generation must try official SportyBet host variants sequentially and report diagnostics without fabricating codes");
assert.ok(booking.includes("fallback_direct_origin:true") && booking.includes("fallback_selections"), "Basketball booking must return verified selections for the same direct-origin fallback pattern as eFootball");
assert.ok(!ui.includes("directOriginBasketballShare") && ui.includes("data.message||data.error"), "Basketball UI must surface the server's official-host diagnostics instead of repeating a browser request blocked by CORS");
assert.ok(ui.includes("./api/sportybet-basketball-booking"), "Builder UI must request a live-validated SportyBet booking code");
assert.ok(booking.includes("host+'/api/ng/orders/share") && booking.includes("booking_code:share.code"), "Basketball booking endpoint must request and return a genuine SportyBet share code through official host variants");
assert.ok(booking.includes("leg.market_id||'225'") && booking.includes("SELECTIONS_CHANGED") && booking.includes("NON_STAKING_BETSLIP_PREPARATION"), "Basketball code generation must revalidate exact total market 225 and fail closed without staking");

assert.ok(ui.includes("nba_live_current.json") && ui.includes("live_total_projection") && ui.includes("score_pace_total"), "Live desk must load the latest ESPN in-game observation and display a separate score-pace estimate.");
assert.ok(ui.includes("Live behavior snapshot is stale or unavailable") && ui.includes("12*60*1000"), "Live insights must fail closed when the observation artifact is stale.");
assert.ok(ui.includes("Pregame probability is unchanged") && ui.includes("Paper research only"), "Live insights must preserve the pre-game forecast and research-only boundary.");
assert.ok(nbaRecorderWorkflow.includes("data/nba_live_current.json") && nbaRecorderWorkflow.includes("git add data/nba_live_observations.json data/nba_live_current.json"), "NBA recorder must publish the compact live artifact alongside its audit history.");
assert.ok(recorder.includes("def live_total_projection") && recorder.includes("pace_total = live_total / elapsed * 48") && recorder.includes("pregame + 18") && recorder.includes("OVERTIME_CONTEXT_ONLY"), "NBA live projection must use score/clock pace, cap the live adjustment, and withhold regulation estimates in overtime.");
console.log("Basketball desk contract passed: shared UI, scoped responsive design, exact SportyBet event matching, fresh totals, and separate timestamp-gated live score-pace insights.");
