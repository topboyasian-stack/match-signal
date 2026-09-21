(function () {
  'use strict';
  var all = [];
  function $(id) { return document.getElementById(id); }
  function pct(v) { var n = Number(v); return isFinite(n) ? Math.round(n * 100) + '%' : '—'; }
  function num(v) { var n = Number(v); return isFinite(n) ? n.toFixed(2) : '—'; }
  function fmt(v) { var d = new Date(v); return isNaN(d.getTime()) ? String(v || '—') : d.toLocaleString(); }
  function esc(v) { var d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }
  function get(path) {
    return fetch('./' + path, { cache: 'default' }).then(function (r) {
      if (!r.ok) throw new Error(path + ' HTTP ' + r.status);
      return r.json();
    });
  }
  function dedupe(rows) {
    var m = new Map();
    (rows || []).forEach(function (x) {
      var k = String(x.event_id || ((x.league || '') + '|' + (x.start_time || '') + '|' + (x.player_1 || '') + '|' + (x.player_2 || '')));
      if (!m.has(k)) m.set(k, x);
    });
    return Array.from(m.values());
  }
  function footballCard(x) {
    var a = x.probabilities || {}, eg = x.expected_goals || {}, markets = x.markets || {}, ou = markets.over_under || {}, bt = markets.btts || {}, hc = x.handicap || {};
    var pick = x.pick === 'p1' ? x.player_1 : x.pick === 'p2' ? x.player_2 : 'Draw';
    var bars = [['1X2 · ' + x.player_1, a.p1], ['Draw', a.draw], ['1X2 · ' + x.player_2, a.p2]];
    return '<article class="card"><div class="meta"><span>⚽ ' + esc(x.league || 'Football') + '</span><span>' + esc(fmt(x.start_time)) + '</span></div><div class="teams">' + esc(x.player_1) + ' <span style="color:var(--muted);font-weight:500">vs</span> ' + esc(x.player_2) + '</div><div class="pick">Model pick: <b>' + esc(pick) + '</b><span class="conf">Confidence ' + pct(x.confidence) + '</span></div><div class="section"><b>1X2 probabilities</b>' + bars.map(function (b) { return '<div class="row"><span>' + esc(b[0]) + '</span><b>' + pct(b[1]) + '</b></div><div class="bar"><div class="fill" style="width:' + Math.round((Number(b[1]) || 0) * 100) + '%"></div></div>'; }).join('') + '</div><div class="section"><b>Goal markets</b><div class="row"><span>Expected goals</span><b>' + num(eg.p1) + ' — ' + num(eg.p2) + ' · total ' + num(eg.total) + '</b></div><div class="row"><span>O/U ' + esc(ou.line == null ? '2.5' : ou.line) + '</span><b>' + pct(ou.over) + ' over · ' + pct(ou.under) + ' under</b></div><div class="row"><span>BTTS</span><b>' + pct(bt.yes) + ' yes · ' + pct(bt.no) + ' no</b></div>' + (hc.home_cover != null ? '<div class="row"><span>Handicap ' + esc(hc.line) + '</span><b>' + pct(hc.home_cover) + ' home cover · ' + pct(hc.away_cover) + ' away</b></div>' : '') + '</div><div class="section sub">Model: ' + esc(x.model || '—') + '<br>Sample: ' + esc(x.signal_quality && x.signal_quality.effective_sample != null ? x.signal_quality.effective_sample : '—') + ' · history events: ' + esc(x.signal_quality && x.signal_quality.history_events != null ? x.signal_quality.history_events : '—') + ' · ' + esc(x.prediction_status || x.decision || 'PAPER ONLY') + '</div></article>';
  }
  function sideName(pick, p1, p2) { var s = String(pick || '').trim().toLowerCase(); if (s === 'p1') return p1; if (s === 'p2') return p2; var m = s.match(/(?:—|-|:)\s*(p1|p2)\s*$/); if (m) return m[1] === 'p1' ? p1 : p2; return pick || '—'; }
  function tennisCard(x) {
    var a = x.probabilities || {}, an = x.analytics || {}, tw = an.total_games || {}, gh = an.games_handicap || {}, rank = x.rankings || {}, form = x.form || {};
    var pick = x.pick === 'p1' ? x.player_1 : x.player_2;
    return '<article class="card"><div class="meta"><span>🎾 ' + esc(x.league || 'Tennis') + ' · ' + esc(x.tournament || '') + '</span><span>' + esc(fmt(x.start_time)) + '</span></div><div class="teams">' + esc(x.player_1) + ' <span style="color:var(--muted);font-weight:500">vs</span> ' + esc(x.player_2) + '</div><div class="pick">Model pick: <b>' + esc(pick) + '</b><span class="conf">Confidence ' + pct(x.confidence) + '</span></div><div class="section"><b>Match probability</b><div class="row"><span>' + esc(x.player_1) + '</span><b>' + pct(a.p1) + '</b></div><div class="bar"><div class="fill" style="width:' + Math.round((Number(a.p1) || 0) * 100) + '%"></div></div><div class="row"><span>' + esc(x.player_2) + '</span><b>' + pct(a.p2) + '</b></div><div class="bar"><div class="fill" style="width:' + Math.round((Number(a.p2) || 0) * 100) + '%"></div></div></div><div class="section"><b>Set / game analytics</b><div class="row"><span>Set win</span><b>' + pct(an.set_win_prob && an.set_win_prob.p1) + ' — ' + pct(an.set_win_prob && an.set_win_prob.p2) + '</b></div><div class="row"><span>Straight sets</span><b>' + pct(an.straight_sets && an.straight_sets.p1) + ' — ' + pct(an.straight_sets && an.straight_sets.p2) + '</b></div><div class="row"><span>Three sets</span><b>' + pct(an.three_sets) + '</b></div><div class="row"><span>Expected sets</span><b>' + num(an.expected_sets) + '</b></div><div class="row"><span>Total games ' + esc(tw.line == null ? '' : tw.line) + '</span><b>' + pct(tw.over) + ' over · ' + pct(tw.under) + ' under</b></div><div class="row"><span>Games handicap</span><b>' + esc(sideName(gh.pick, x.player_1, x.player_2)) + '</b></div></div><div class="section sub">Rankings: ' + esc(rank.p1 == null ? '—' : rank.p1) + ' vs ' + esc(rank.p2 == null ? '—' : rank.p2) + ' · form: ' + esc(form.p1_last10 || '—') + ' vs ' + esc(form.p2_last10 || '—') + '<br>Model: ' + esc(x.model || '—') + ' · components ' + esc(x.signal_quality && x.signal_quality.components != null ? x.signal_quality.components : '—') + '/' + esc(x.signal_quality && x.signal_quality.max_components != null ? x.signal_quality.max_components : '—') + ' · ' + esc(x.decision || 'PAPER ONLY') + '</div></article>';
  }
  function render() {
    var sf = $('sportFilter').value, lf = $('leagueFilter').value, q = $('search').value.trim().toLowerCase();
    var rows = all.filter(function (x) { return (sf === 'all' || x.sport === sf) && (lf === 'all' || x.league === lf) && (!q || ((x.player_1 || '') + ' ' + (x.player_2 || '') + ' ' + (x.league || '') + ' ' + (x.tournament || '')).toLowerCase().indexOf(q) !== -1); });
    var grouped = {};
    rows.forEach(function (x) { var k = x.league || x.sport || 'Other'; if (!grouped[k]) grouped[k] = []; grouped[k].push(x); });
    var keys = Object.keys(grouped).sort();
    var limit = 30;
    $('groups').innerHTML = keys.map(function (k) {
      var list = grouped[k], shown = list.slice(0, limit);
      return '<div class="group"><h2>' + esc(k) + '</h2><div class="groupMeta">' + list.length + ' detailed fixture' + (list.length === 1 ? '' : 's') + (list.length > limit ? ' · showing first ' + limit : '') + '</div><div class="grid">' +
        shown.map(function (x) { return x.sport === 'tennis' ? tennisCard(x) : footballCard(x); }).join('') +
        (list.length > limit ? '<button class="btn ms-load-more" data-league="' + esc(k) + '" style="margin-top:12px">Show remaining ' + (list.length-limit) + '</button>' : '') +
        '</div></div>';
    }).join('') || '<div class="empty">No fixtures match the selected filters.</div>';
    Array.from(document.querySelectorAll('.ms-load-more')).forEach(function(btn){
      btn.onclick=function(){
        var league=btn.getAttribute('data-league'), target=grouped[league]||[];
        var grid=btn.parentElement, current=grid.querySelectorAll('.card').length;
        var next=target.slice(0,current+30);
        grid.querySelectorAll('.card').forEach(function(el){el.remove();});
        var cards=next.map(function(x){return x.sport==='tennis'?tennisCard(x):footballCard(x);}).join('');
        grid.insertAdjacentHTML('afterbegin',cards);
        if(next.length>=target.length) btn.remove(); else btn.textContent='Show remaining '+(target.length-next.length);
      };
    });
  }
  function filters() {
    var leagues = Array.from(new Set(all.map(function (x) { return x.league; }).filter(Boolean))).sort();
    $('leagueFilter').innerHTML = '<option value="all">All leagues / tours</option>' + leagues.map(function (x) { return '<option value="' + esc(x) + '">' + esc(x) + '</option>'; }).join('');
    $('sportFilter').onchange = render; $('leagueFilter').onchange = render; $('search').oninput = render;
  }
  window.run = function () {
    $('status').textContent = 'Loading all prediction feeds…';
    Promise.allSettled([get('data/predictions.json'), get('data/ere_divisie_predictions.json')]).then(function (parts) {
      var main = parts[0].status === 'fulfilled' && Array.isArray(parts[0].value) ? parts[0].value : []; var ere = parts[1].status === 'fulfilled' && Array.isArray(parts[1].value) ? parts[1].value : []; all = dedupe(main.concat(ere));
      $('fixtures').textContent = all.length; $('football').textContent = all.filter(function (x) { return x.sport === 'football'; }).length; $('tennis').textContent = all.filter(function (x) { return x.sport === 'tennis'; }).length; $('leagues').textContent = new Set(all.map(function (x) { return x.league; }).filter(Boolean)).size;
      $('status').textContent = all.length + ' detailed predictions loaded'; $('updated').textContent = 'Feed checked ' + new Date().toLocaleString() + ' · main: ' + main.length + ' · Eredivisie: ' + ere.length; filters(); render();
    }).catch(function (e) {
      $('status').textContent = 'Expansion data unavailable'; $('updated').innerHTML = '<span style="color:var(--red)">' + esc(e.message) + '</span>'; $('groups').innerHTML = '<div class="empty">' + esc(e.message) + '</div>';
    });
  };
  window.run();
  window.setInterval(window.run, 120000);
}());
