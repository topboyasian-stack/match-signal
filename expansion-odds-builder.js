(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(v) { var d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }
  function pct(v) { var n = Number(v); return isFinite(n) ? (n * 100).toFixed(1) + '%' : '—'; }
  function parseStart(v) { var d = v ? new Date(v) : null; return d && !isNaN(d.getTime()) ? d : null; }
  function players(match) {
    var parts = String(match || '').split(/\s+vs\.?\s+/i);
    return { p1: (parts[0] || '').trim(), p2: (parts[1] || '').trim() };
  }
  function selectionInfo(leg) {
    var ps = players(leg.match);
    var rawPick = String(leg.pick || '').trim();
    var pick = rawPick.toLowerCase();
    var positionMatch = pick.match(/(?:—|-|:)\s*(p1|p2)\s*$/i);
    var position = positionMatch ? positionMatch[1].toLowerCase() : pick;
    if ((leg.market === 'winner' || leg.market === 'games_handicap') && (position === 'p1' || position === 'p2')) {
      var pos = position.toUpperCase();
      var player = position === 'p1' ? ps.p1 : ps.p2;
      return { position: pos, player: player, text: pos + ' · ' + player };
    }
    return { position: '', player: '', text: rawPick.replace(/^.*?—\s*/, '') || '—' };
  }
  function formatElapsed(diff) {
    var total = Math.max(0, Math.floor(diff / 1000));
    var days = Math.floor(total / 86400); total %= 86400;
    var hours = Math.floor(total / 3600); total %= 3600;
    var mins = Math.floor(total / 60); var secs = total % 60;
    if (days) return days + 'd ' + String(hours).padStart(2, '0') + 'h ' + String(mins).padStart(2, '0') + 'm';
    return String(hours).padStart(2, '0') + 'h ' + String(mins).padStart(2, '0') + 'm ' + String(secs).padStart(2, '0') + 's';
  }
  function timerState(v, settlement) {
    var d = parseStart(v);
    if (settlement && settlement.settled) return { text: 'ENDED · SETTLED', label: 'Result', state: settlement.correct ? 'settled-correct' : 'settled-wrong' };
    if (!d) return { text: 'Start time unavailable', label: 'Status', state: 'unknown' };
    var diff = d.getTime() - Date.now();
    if (diff > 0) {
      var total = Math.floor(diff / 1000), days = Math.floor(total / 86400); total %= 86400;
      var hours = Math.floor(total / 3600); total %= 3600; var mins = Math.floor(total / 60); var secs = total % 60;
      var text = days > 0 ? days + 'd ' + String(hours).padStart(2, '0') + 'h ' + String(mins).padStart(2, '0') + 'm' : String(hours).padStart(2, '0') + 'h ' + String(mins).padStart(2, '0') + 'm ' + String(secs).padStart(2, '0') + 's';
      return { text: text, label: 'Starts in', state: diff <= 15 * 60 * 1000 ? 'soon' : 'upcoming' };
    }
    return { text: 'LIVE · ' + formatElapsed(Date.now() - d.getTime()), label: 'Live play', state: 'live' };
  }
  function localStart(v) {
    var d = parseStart(v);
    if (!d) return '—';
    return d.toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  }
  function settlementFromRecord(r) {
    if (!r || r.settled !== true) return null;
    var pick = String(r.pick || '').toLowerCase();
    var actual = String(r.actual || '').toLowerCase();
    var correct = null;
    if (r.market === 'total_games' || r.market === 'total_goals' || r.market === 'over_under') {
      var markets = r.actual_markets || {};
      actual = String(markets.total_games_result || markets.total_goals_result || markets.over_under_result || r.actual || '').toLowerCase();
      if (actual) correct = pick === actual;
    } else if (pick && actual) {
      correct = pick === actual;
    }
    if (correct === null) return null;
    return { settled: true, correct: !!correct, actual: r.actual || actual || '—', settledAt: r.settled_at };
  }
  var settlementMap = {};
  function loadOne(path) {
    return fetch('./data/' + path + '?v=' + Date.now(), { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error(path + ' HTTP ' + r.status);
      return r.json();
    }).catch(function () { return []; });
  }
  function loadSettlements() {
    return Promise.all([loadOne('tennis_prediction_archive.json'), loadOne('prediction_history.json')]).then(function (sets) {
      settlementMap = {};
      sets.forEach(function (rows) {
        (Array.isArray(rows) ? rows : []).forEach(function (r) {
          if (r && r.event_id != null) {
            var s = settlementFromRecord(r);
            if (s) settlementMap[String(r.event_id)] = s;
          }
        });
      });
    });
  }
  function timerMarkup(v, eventId) {
    var c = timerState(v, settlementMap[String(eventId || '')]);
    return '<div class="timer ' + c.state + '" data-start="' + esc(v || '') + '" data-event-id="' + esc(eventId || '') + '"><span class="timerLabel">' + esc(c.label) + '</span><strong class="timerValue">' + esc(c.text) + '</strong></div>';
  }
  function cardStyle(settlement) {
    if (!settlement) return '';
    return settlement.correct ? ' style="border-color:#35d49a;background:linear-gradient(180deg,#10291f,#171d2d)"' : ' style="border-color:#ff7474;background:linear-gradient(180deg,#30191d,#171d2d)"';
  }
  function resultMarkup(settlement) {
    if (!settlement) return '';
    var actual = settlement.actual || '—';
    return '<div style="margin-top:10px;padding:10px 12px;border-radius:9px;border:1px solid ' + (settlement.correct ? '#35d49a' : '#ff7474') + ';color:' + (settlement.correct ? '#35d49a' : '#ff7474') + ';font-weight:800">' + (settlement.correct ? '✓ PREDICTION CORRECT' : '✕ PREDICTION INCORRECT') + ' · Actual: ' + esc(actual) + '</div>';
  }
  function load() {
    Promise.all([
      fetch('./data/odds_builder.json?v=' + Date.now(), { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('odds_builder.json HTTP ' + r.status); return r.json(); }),
      loadSettlements()
    ]).then(function (res) { render(res[0]); }).catch(function (e) {
      $('oddsBuilder').innerHTML = '<div class="empty">Accumulator data unavailable: ' + esc(e.message) + '</div>';
    });
  }
  function render(x) {
    var legs = x.qualified_legs || [];
    var cards = legs.map(function (l, i) {
      var sport = String(l.sport || 'football').toLowerCase();
      var competition = l.competition || (sport === 'tennis' ? 'Tennis' : 'Football');
      var settlement = settlementMap[String(l.event_id || '')] || null;
      var sel = selectionInfo(l);
      return '<div class="card"' + cardStyle(settlement) + '><div class="meta"><span>Leg ' + (i + 1) + ' · ' + esc(sport.toUpperCase()) + ' · ' + esc(competition) + '</span><span>Fair odds ' + esc(l.model_fair_odds) + '</span></div><div class="teams">' + esc(l.match) + '</div><div class="pick">Selection: <b>' + esc(sel.text) + '</b>' + (sel.position ? '<small style="display:block;color:var(--muted);margin-top:4px">Model position: ' + esc(sel.position) + '</small>' : '') + '<span class="conf">Model ' + pct(l.model_probability) + '</span></div>' + timerMarkup(l.start_time, l.event_id) + '<div class="startTime">Kickoff / start: ' + esc(localStart(l.start_time)) + ' <span>· your browser time</span></div>' + resultMarkup(settlement) + '<div class="section"><div class="row"><span>Market</span><b>' + esc(l.market || '—') + '</b></div><div class="row"><span>Model fair odds</span><b>' + esc(l.model_fair_odds) + '</b></div><div class="row"><span>Actual bookmaker odds</span><b>Verify manually</b></div></div></div>';
    }).join('');
    var status = x.status === 'QUALIFIED_ACCUMULATOR' ? 'READY FOR MANUAL BUILD' : (x.status || '—');
    $('oddsBuilder').innerHTML = '<div class="metrics"><div class="metric"><small>Qualified legs</small><strong>' + legs.length + '/4</strong></div><div class="metric"><small>Sports</small><strong>' + esc(legs.length ? Array.from(new Set(legs.map(function (l) { return String(l.sport || '').toUpperCase(); }))).join(' + ') : '—') + '</strong></div><div class="metric"><small>Status</small><strong>' + esc(status) + '</strong></div><div class="metric"><small>Reference combined odds</small><strong>' + esc(x.reference_combined_odds == null ? '—' : x.reference_combined_odds) + '</strong></div></div><div class="panel"><b>Manual 3–4 Selection Accumulator · Football + Tennis</b><div class="sub">Selections use the model's explicit P1/P2 position. Timers count down before start, continue as a live elapsed timer after start, and switch to ENDED · SETTLED when the prediction ledger records the final result. Settled correct predictions are green; incorrect predictions are red.</div><div class="grid" style="margin-top:14px">' + (cards || '<div class="empty">No 3–4 selection set currently qualifies. The system will not force an accumulator.</div>') + '</div><div class="section"><div class="row"><span>Bookmaker price</span><b>Manual confirmation required</b></div><div class="row"><span>SportyBet direct feed</span><b>' + esc((x.bookmaker_odds || {}).sportybet_direct_feed || 'Not used') + '</b></div><div class="row"><span>Combined odds</span><b>Recalculate from the actual odds shown in your betslip</b></div></div></div>';
    updateTimers();
  }
  function updateTimers() {
    document.querySelectorAll('#oddsBuilder .timer[data-start]').forEach(function (el) {
      var c = timerState(el.getAttribute('data-start'), settlementMap[el.getAttribute('data-event-id')]);
      el.className = 'timer ' + c.state;
      var label = el.querySelector('.timerLabel'); var value = el.querySelector('.timerValue');
      if (label) label.textContent = c.label;
      if (value) value.textContent = c.text;
    });
  }
  window.loadOddsBuilder = load;
  load();
  window.setInterval(updateTimers, 1000);
  window.setInterval(load, 60000);
}());
