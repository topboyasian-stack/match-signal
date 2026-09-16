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
      $('oddsBuilder').innerHTML = '<div class="empty">Odds Builder data unavailable: ' + esc(e.message) + '</div>';
    });
  }
  function render(x) {
    var sb = x.sportybet || {}, st = x.stake || {}, legs = x.qualified_legs || [];
    var cards = legs.map(function (l, i) {
      return '<div class="card"><div class="meta"><span>Leg ' + (i + 1) + ' · ' + esc(l.league || 'Football') + '</span><span>Odds ' + esc(l.sporty_odds) + '</span></div><div class="teams">' + esc(l.home) + ' <span style="color:var(--muted);font-weight:500">vs</span> ' + esc(l.away) + '</div><div class="pick">Selection: <b>' + esc(l.selection || l.pick) + '</b><span class="conf">Model ' + pct(l.model_probability) + '</span></div><div class="section"><div class="row"><span>SportyBet odds</span><b>' + esc(l.sporty_odds) + '</b></div><div class="row"><span>Implied probability</span><b>' + pct(l.implied_probability) + '</b></div><div class="row"><span>Model edge</span><b>' + pct(l.edge) + '</b></div></div></div>';
    }).join('');
    var booking = sb.booking_code ? '<a class="btn" href="' + esc(sb.share_url || '#') + '" target="_blank" rel="noopener">Open SportyBet slip</a><div class="row"><span>SportyBet booking code</span><b>' + esc(sb.booking_code) + '</b></div>' : '<div class="sub">SportyBet booking code: ' + esc(sb.status || 'not available') + '</div>';
    $('oddsBuilder').innerHTML = '<div class="metrics"><div class="metric"><small>Qualified legs</small><strong>' + legs.length + '/4</strong></div><div class="metric"><small>SportyBet</small><strong>' + esc(sb.status || '—') + '</strong></div><div class="metric"><small>Combined odds</small><strong>' + esc(sb.combined_odds == null ? '—' : sb.combined_odds) + '</strong></div><div class="metric"><small>Stake</small><strong>' + esc(st.status || '—') + '</strong></div></div><div class="panel"><b>Trusted 3–4 selection builder</b><div class="sub">The builder only consumes selections that passed the upstream research gate. It does not alter the public prediction feed. Booking codes are bookmaker-generated; no staking or wager submission occurs here.</div><div class="grid" style="margin-top:14px">' + (cards || '<div class="empty">No 3–4 selection set currently qualifies. The system will not force a slip.</div>') + '</div><div class="section">' + booking + '</div></div>';
  }
  window.loadOddsBuilder = load;
  load();
  window.setInterval(load, 60000);
}());
