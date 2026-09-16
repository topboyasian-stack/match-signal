(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(v) { var d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }
  function pct(v) { var n = Number(v); return isFinite(n) ? (n * 100).toFixed(1) + '%' : '—'; }
  function load() {
    fetch('./data/odds_builder.json?v=' + Date.now(), { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('odds_builder.json HTTP ' + r.status);
      return r.json();
    }).then(render).catch(function (e) {
      $('oddsBuilder').innerHTML = '<div class="empty">Accumulator data unavailable: ' + esc(e.message) + '</div>';
    });
  }
  function render(x) {
    var legs = x.qualified_legs || [];
    var cards = legs.map(function (l, i) {
      var sport = String(l.sport || 'football').toLowerCase();
      var competition = l.competition || (sport === 'tennis' ? 'Tennis' : 'Football');
      return '<div class="card"><div class="meta"><span>Leg ' + (i + 1) + ' · ' + esc(sport.toUpperCase()) + ' · ' + esc(competition) + '</span><span>Fair odds ' + esc(l.model_fair_odds) + '</span></div><div class="teams">' + esc(l.match) + '</div><div class="pick">Selection: <b>' + esc(l.pick) + '</b><span class="conf">Model ' + pct(l.model_probability) + '</span></div><div class="section"><div class="row"><span>Market</span><b>' + esc(l.market || '—') + '</b></div><div class="row"><span>Model fair odds</span><b>' + esc(l.model_fair_odds) + '</b></div><div class="row"><span>Actual bookmaker odds</span><b>Verify manually</b></div><div class="row"><span>Start</span><b>' + esc(l.start_time || '—') + '</b></div></div></div>';
    }).join('');
    var status = x.status === 'QUALIFIED_ACCUMULATOR' ? 'READY FOR MANUAL BUILD' : (x.status || '—');
    $('oddsBuilder').innerHTML = '<div class="metrics"><div class="metric"><small>Qualified legs</small><strong>' + legs.length + '/4</strong></div><div class="metric"><small>Sports</small><strong>' + esc(legs.length ? Array.from(new Set(legs.map(function (l) { return String(l.sport || '').toUpperCase(); }))).join(' + ') : '—') + '</strong></div><div class="metric"><small>Status</small><strong>' + esc(status) + '</strong></div><div class="metric"><small>Reference combined odds</small><strong>' + esc(x.reference_combined_odds == null ? '—' : x.reference_combined_odds) + '</strong></div></div><div class="panel"><b>Manual 3–4 Selection Accumulator · Football + Tennis</b><div class="sub">The booking/share-code layer has been removed. Match Signal supplies the research-qualified selections and model fair odds; you manually find the same selections on SportyBet or Stake and confirm the live bookmaker prices before placing your own accumulator. Reference combined odds are model fair odds, not bookmaker prices. The public prediction feed remains unchanged.</div><div class="grid" style="margin-top:14px">' + (cards || '<div class="empty">No 3–4 selection set currently qualifies. The system will not force an accumulator.</div>') + '</div><div class="section"><div class="row"><span>Bookmaker price</span><b>Manual confirmation required</b></div><div class="row"><span>SportyBet direct feed</span><b>' + esc((x.bookmaker_odds || {}).sportybet_direct_feed || 'Not used') + '</b></div><div class="row"><span>Combined odds</span><b>Recalculate from the actual odds shown in your betslip</b></div></div></div>';
  }
  window.loadOddsBuilder = load;
  load();
  window.setInterval(load, 60000);
}());
