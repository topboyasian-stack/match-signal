(function () {
  'use strict';

  function esc(v) {
    var d = document.createElement('div');
    d.textContent = v == null ? '' : String(v);
    return d.innerHTML;
  }

  function pct(v) {
    var n = Number(v);
    return isFinite(n) ? (n * 100).toFixed(1) + '%' : '—';
  }

  function num(v) {
    var n = Number(v);
    return isFinite(n) ? n.toFixed(2) : '—';
  }

  function sideName(pick, p1, p2) { var s = String(pick || '').trim().toLowerCase(); if (s === 'p1') return p1; if (s === 'p2') return p2; var m = s.match(/(?:—|-|:)\s*(p1|p2)\s*$/); if (m) return m[1] === 'p1' ? p1 : p2; return pick || '—'; }\n\n  function fmt(v) {
    var d = new Date(v);
    return isNaN(d.getTime()) ? String(v || '—') : d.toLocaleString();
  }

  function getPredictions() {
    return fetch('./data/predictions.json?v=' + Date.now(), { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('data/predictions.json HTTP ' + r.status);
      return r.json();
    });
  }

  function render(rows) {
    var existing = document.getElementById('tennisOuRoadmap');
    if (existing) existing.remove();
    var tennis = (Array.isArray(rows) ? rows : []).filter(function (x) { return x && x.sport === 'tennis'; });
    var section = document.createElement('section');
    section.id = 'tennisOuRoadmap';
    section.className = 'panel';
    section.innerHTML = '<b>🎾 Tennis O/U roadmap</b>' +
      '<div class="sub">Private roadmap view only. The public Tennis page is unchanged. Probabilities are shown to one decimal place so fixture-level differences are visible.</div>' +
      '<div id="tennisOuGrid" class="grid" style="margin-top:12px"></div>';
    var groups = document.getElementById('groups');
    var host = groups && groups.parentElement;
    if (!host) return;
    host.insertBefore(section, groups);
    var grid = document.getElementById('tennisOuGrid');
    var withOu = tennis.filter(function (x) { return x.analytics && x.analytics.total_games && x.analytics.total_games.line != null; });
    if (!withOu.length) { grid.innerHTML = '<div class="empty">No tennis total-games O/U markets are currently published.</div>'; return; }
    grid.innerHTML = withOu.map(function (x) {
      var a = x.analytics || {}, ou = a.total_games || {}, gh = a.games_handicap || {};
      var expectedGames = a.expected_games != null ? a.expected_games : (a.total_games_expected != null ? a.total_games_expected : null);
      var pick = ou.pick ? String(ou.pick).toUpperCase() : '—';
      return '<article class="card">' +
        '<div class="meta"><span>🎾 ' + esc(x.league || 'Tennis') + ' · ' + esc(x.tournament || '') + '</span><span>' + esc(fmt(x.start_time)) + '</span></div>' +
        '<div class="teams">' + esc(x.player_1) + ' <span style="color:var(--muted);font-weight:500">vs</span> ' + esc(x.player_2) + '</div>' +
        '<div class="pick">Games O/U <b>' + esc(pick) + ' ' + esc(ou.line) + '</b><span class="conf">' + (ou.pick === 'over' ? pct(ou.over) : ou.pick === 'under' ? pct(ou.under) : '—') + '</span></div>' +
        '<div class="section"><b>Total-games probabilities</b>' +
        '<div class="row"><span>Over ' + esc(ou.line) + '</span><b>' + pct(ou.over) + '</b></div>' +
        '<div class="bar"><div class="fill" style="width:' + Math.round((Number(ou.over) || 0) * 100) + '%"></div></div>' +
        '<div class="row"><span>Under ' + esc(ou.line) + '</span><b>' + pct(ou.under) + '</b></div>' +
        '<div class="bar"><div class="fill" style="width:' + Math.round((Number(ou.under) || 0) * 100) + '%"></div></div>' +
        (expectedGames != null ? '<div class="row"><span>Expected total games</span><b>' + num(expectedGames) + '</b></div>' : '') +
        '</div>' +
        '<div class="section sub">Match probability: ' + pct(x.probabilities && x.probabilities.p1) + ' / ' + pct(x.probabilities && x.probabilities.p2) + ' · Games handicap: ' + esc(sideName(gh.pick, x.player_1, x.player_2)) + '<br>Model: ' + esc(x.model || '—') + ' · Decision: ' + esc(x.decision || 'PAPER ONLY') + '</div>' +
        '</article>';
    }).join('');
  }

  function refresh() {
    getPredictions().then(render).catch(function (e) {
      var old = document.getElementById('tennisOuRoadmap'); if (old) old.remove();
      var groups = document.getElementById('groups'); if (!groups || !groups.parentElement) return;
      var section = document.createElement('section'); section.id = 'tennisOuRoadmap'; section.className = 'panel';
      section.innerHTML = '<b>🎾 Tennis O/U roadmap</b><div class="sub" style="color:var(--red)">Unable to load tennis O/U data: ' + esc(e.message) + '</div>';
      groups.parentElement.insertBefore(section, groups);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', refresh); else refresh();
  window.setInterval(refresh, 60000);
}());
