/* Shared floating ticket box: NBA release-gated builders plus manual football/tennis slips. */
(function () {
  'use strict';
  var params = new URLSearchParams(window.location.search);
  var embedMode = params.get('builderOnly') === '1' || params.get('embed') === '1';
  if (embedMode) {
    document.documentElement.classList.add('builder-only-mode');
    return;
  }
  var sport = String(document.body && document.body.getAttribute('data-sport') || '').toLowerCase();
  if (['football', 'tennis', 'basketball'].indexOf(sport) === -1) return;
  if (document.getElementById('msTicketLauncher')) return;

  var isBasketball = sport === 'basketball';
  var builderUrl = './basketball.html?builderOnly=1&drawer=1#basketball-builders';
  var fullUrl = isBasketball ? './basketball.html#basketball-builders' : './' + sport + '.html';
  var title = isBasketball ? 'Basketball ticket builders' : 'SportyBet ticket box';
  var subtitle = isBasketball
    ? 'NBA totals · four builders · release gate applies'
    : sport.charAt(0).toUpperCase() + sport.slice(1) + ' · select live-priced winners';

  var launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.id = 'msTicketLauncher';
  launcher.className = 'ms-ticket-launcher';
  launcher.setAttribute('aria-haspopup', 'dialog');
  launcher.setAttribute('aria-controls', 'msTicketDrawer');
  launcher.setAttribute('aria-expanded', 'false');
  launcher.innerHTML = '<span class="ms-ticket-launcher-mark" aria-hidden="true">🎟</span><span class="ms-ticket-launcher-copy"><span>SportyBet Ticket Box</span><small>Tap to open slip</small></span>';

  var backdrop = document.createElement('button');
  backdrop.type = 'button';
  backdrop.className = 'ms-ticket-backdrop';
  backdrop.setAttribute('aria-label', 'Close SportyBet ticket box');
  backdrop.hidden = true;

  var drawer = document.createElement('aside');
  drawer.id = 'msTicketDrawer';
  drawer.className = 'ms-ticket-drawer';
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-modal', 'true');
  drawer.setAttribute('aria-label', title);
  drawer.hidden = true;
  drawer.innerHTML =
    '<div class="ms-ticket-drawer-head">' +
      '<div class="ms-ticket-heading"><span class="ms-ticket-heading-icon" aria-hidden="true">🎟</span><div class="ms-ticket-heading-copy"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(subtitle) + '</p></div></div>' +
      '<div class="ms-ticket-head-actions"><a class="ms-ticket-full-link" href="' + fullUrl + '" target="_blank" rel="noopener">Desk ↗</a><button type="button" class="ms-ticket-close" data-ticket-close aria-label="Close ticket box">×</button></div>' +
    '</div>' +
    '<div class="ms-ticket-policy"><span class="ms-ticket-policy-icon" aria-hidden="true">●</span><span><b>Manual slip · no auto-betting.</b> Football/tennis selections are checked against current SportyBet markets again before a code is requested. NBA totals remain locked until the independent release evidence qualifies.</span></div>' +
    (isBasketball
      ? '<div class="ms-ticket-frame-wrap"><div class="ms-ticket-frame-loading" role="status">Loading the NBA four-builder workspace…</div><iframe class="ms-ticket-frame" title="Basketball ticket builders" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe></div>'
      : manualBuilderMarkup(sport));

  document.body.appendChild(launcher);
  document.body.appendChild(backdrop);
  document.body.appendChild(drawer);
  var closeButton = drawer.querySelector('[data-ticket-close]');
  var frame = drawer.querySelector('iframe');
  var frameWrap = drawer.querySelector('.ms-ticket-frame-wrap');
  var loaded = false;
  var previousFocus = null;
  var feedSport = sport;
  var feedEvents = [];
  var feedFetchedAt = 0;
  var feedBusy = false;
  var feedError = '';
  var slip = loadSlip();
  var lastBooking = null;

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function manualBuilderMarkup(sportKey) {
    return '<div class="ms-ticket-manual" data-sport="' + sportKey + '">' +
      '<div class="ms-ticket-feed-row"><div><b>Current SportyBet fixtures</b><small data-ms-feed-status>Loading verified markets…</small></div><button type="button" data-ms-feed-refresh>Refresh</button></div>' +
      '<label class="ms-ticket-fixture-label" for="msTicketFixture">Choose a pre-match fixture</label>' +
      '<select id="msTicketFixture" data-ms-ticket-fixture><option value="">Loading fixtures…</option></select>' +
      '<div class="ms-ticket-outcomes" data-ms-ticket-outcomes><div class="ms-ticket-empty">Select a fixture to load its current winner prices.</div></div>' +
      '<div class="ms-ticket-slip">' +
        '<div class="ms-ticket-slip-head"><div><b>Your slip</b><small data-ms-slip-count>0 selections · 2 required</small></div><strong data-ms-combined-odds>Combined odds —</strong></div>' +
        '<div class="ms-ticket-slip-legs" data-ms-slip-legs><div class="ms-ticket-empty">Choose a football or tennis outcome above, then add it to the slip.</div></div>' +
        '<div class="ms-ticket-generate-row"><button type="button" class="ms-ticket-generate" data-ms-ticket-generate disabled>Generate SportyBet code</button><button type="button" class="ms-ticket-clear" data-ms-ticket-clear disabled>Clear</button></div>' +
        '<div class="ms-ticket-result" data-ms-ticket-result role="status">A code can be requested when at least two different events are selected.</div>' +
        '<p class="ms-ticket-fineprint">Quotes shown here are read-only. The booking endpoint rechecks event identity, start time, winner market and outcome IDs. Confirm the final slip and odds on SportyBet yourself.</p>' +
      '</div></div>';
  }
  function loadSlip() {
    try {
      var value = JSON.parse(localStorage.getItem('match-signal:sportybet-manual-ticket:v1') || '[]');
      return Array.isArray(value) ? value.filter(function (x) { return x && x.event_id && x.sport; }).slice(0, 20) : [];
    } catch (_) { return []; }
  }
  function saveSlip() {
    try { localStorage.setItem('match-signal:sportybet-manual-ticket:v1', JSON.stringify(slip)); } catch (_) {}
  }
  function normalizeName(value) { return String(value || '').toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' '); }
  function activeOutcome(outcome) {
    if (outcome && outcome.isActive != null) return outcome.isActive === true || Number(outcome.isActive) === 1;
    return !outcome || outcome.active !== false;
  }
  function startMillis(value) {
    var n = Number(value || 0);
    if (Number.isFinite(n) && n > 0) return n < 100000000000 ? n * 1000 : n;
    var parsed = Date.parse(String(value || ''));
    return Number.isFinite(parsed) ? parsed : 0;
  }
  function normalizeRawEvent(event, tournament) {
    var start = startMillis(event && (event.estimateStartTime || event.startTime || event.start_time_ms || event.start_time));
    var home = String(event && (event.homeTeamName || (event.homeTeam && event.homeTeam.name)) || '');
    var away = String(event && (event.awayTeamName || (event.awayTeam && event.awayTeam.name)) || '');
    var matchStatus = String(event && (event.matchStatus || event.status || '') || 'Not start');
    return {
      event_id: String(event && (event.eventId || event.id) || ''),
      home: home, away: away, start_time_ms: start,
      start_time: start ? new Date(start).toISOString() : '',
      match_status: matchStatus,
      tournament: String(tournament && tournament.name || ''),
      sport: sport, markets: Array.isArray(event && event.markets) ? event.markets : []
    };
  }
  function winnerMarket(event) {
    var markets = Array.isArray(event && event.markets) ? event.markets : [];
    for (var i = 0; i < markets.length; i++) {
      var market = markets[i];
      var id = String(market && (market.id || market.marketId) || '');
      var desc = String(market && (market.desc || market.name || market.title) || '').toLowerCase();
      if (id === '1' || /3.?way|1x2|match winner|winner/.test(desc) ||
          (sport === 'tennis' && ['186', '210'].indexOf(id) >= 0)) return market;
    }
    return null;
  }
  function outcomeSide(outcome, event) {
    var name = normalizeName(outcome && (outcome.desc || outcome.name || outcome.title));
    if (/^(draw|x)$/.test(name)) return sport === 'football' ? 'draw' : '';
    if (name === normalizeName(event.home) || /^(home|1|p1|player 1)$/.test(name)) return 'p1';
    if (name === normalizeName(event.away) || /^(away|2|p2|player 2)$/.test(name)) return 'p2';
    return '';
  }
  function optionsFor(event) {
    var market = winnerMarket(event);
    if (!market) return [];
    return (Array.isArray(market.outcomes) ? market.outcomes : []).filter(activeOutcome).map(function (outcome) {
      var pick = outcomeSide(outcome, event), odds = Number(outcome && outcome.odds);
      if (!pick || !Number.isFinite(odds) || odds <= 1) return null;
      return { pick: pick, odds: odds, name: String(outcome.desc || outcome.name || outcome.title || pick) };
    }).filter(Boolean).filter(function (x, i, list) {
      return list.findIndex(function (y) { return y.pick === x.pick; }) === i;
    });
  }
  function fmtTime(value) {
    var d = new Date(value);
    if (isNaN(d.getTime())) return 'Time TBC';
    try { return d.toLocaleString('en-NG', { timeZone: 'Africa/Lagos', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch (_) { return d.toLocaleString(); }
  }
  function renderFeedStatus() {
    var el = drawer.querySelector('[data-ms-feed-status]');
    if (!el) return;
    if (feedBusy) el.textContent = 'Refreshing live prices…';
    else if (feedError) el.textContent = feedError;
    else el.textContent = feedEvents.length + ' upcoming matches · quotes rechecked at code generation' + (feedFetchedAt ? ' · refreshed ' + fmtTime(feedFetchedAt) : '');
  }
  function renderFixtures() {
    var select = drawer.querySelector('[data-ms-ticket-fixture]');
    if (!select) return;
    var old = select.value;
    var rows = feedEvents.filter(function (event) { return optionsFor(event).length >= 2; });
    select.innerHTML = '<option value="">Choose fixture…</option>' + rows.map(function (event) {
      return '<option value="' + escapeHtml(event.event_id) + '">' + escapeHtml(event.home + ' vs ' + event.away + ' · ' + fmtTime(event.start_time)) + '</option>';
    }).join('');
    if (old && rows.some(function (x) { return x.event_id === old; })) select.value = old;
    renderOutcomes();
  }
  function selectedEvent() {
    var select = drawer.querySelector('[data-ms-ticket-fixture]');
    var id = select && select.value;
    return feedEvents.find(function (x) { return x.event_id === id; }) || null;
  }
  function renderOutcomes() {
    var host = drawer.querySelector('[data-ms-ticket-outcomes]');
    if (!host) return;
    var event = selectedEvent();
    if (!event) { host.innerHTML = '<div class="ms-ticket-empty">Select a fixture to load its current winner prices.</div>'; return; }
    var options = optionsFor(event);
    host.innerHTML = '<div class="ms-ticket-outcome-title"><b>' + escapeHtml(event.home + ' vs ' + event.away) + '</b><small>' + escapeHtml(fmtTime(event.start_time)) + ' · ' + escapeHtml(event.tournament || sport.toUpperCase()) + '</small></div>' +
      '<div class="ms-ticket-outcome-grid">' + options.map(function (option) {
        var label = option.pick === 'p1' ? event.home : option.pick === 'p2' ? event.away : 'Draw';
        return '<button type="button" class="ms-ticket-outcome" data-ms-add-pick="' + option.pick + '" data-ms-odds="' + option.odds + '"><span>' + escapeHtml(label) + '</span><b>' + option.odds.toFixed(2) + '</b><small>Add selection +</small></button>';
      }).join('') + '</div>';
  }
  function renderSlip() {
    var host = drawer.querySelector('[data-ms-slip-legs]');
    if (!host) return;
    var combined = slip.reduce(function (product, item) { return product * Number(item.odds || 1); }, 1);
    var count = drawer.querySelector('[data-ms-slip-count]');
    var combinedEl = drawer.querySelector('[data-ms-combined-odds]');
    var generate = drawer.querySelector('[data-ms-ticket-generate]');
    var clear = drawer.querySelector('[data-ms-ticket-clear]');
    if (count) count.textContent = slip.length + ' selection' + (slip.length === 1 ? '' : 's') + ' · ' + (slip.length < 2 ? '2 required' : 'ready to recheck');
    if (combinedEl) combinedEl.textContent = slip.length ? 'Indicative odds ' + combined.toFixed(3) + 'x' : 'Combined odds —';
    if (generate) generate.disabled = slip.length < 2 || slip.length > 20 || feedBusy;
    if (clear) clear.disabled = slip.length === 0;
    host.innerHTML = slip.length ? slip.map(function (item, index) {
      return '<div class="ms-ticket-slip-leg"><div><b>' + escapeHtml(item.display_pick) + '</b><small>' + escapeHtml(item.match) + ' · ' + escapeHtml(item.sport) + '</small><small>' + escapeHtml(fmtTime(item.start_time)) + ' · selected @ ' + Number(item.odds).toFixed(2) + '</small></div><button type="button" data-ms-remove-pick="' + index + '" aria-label="Remove ' + escapeHtml(item.display_pick) + '">×</button></div>';
    }).join('') : '<div class="ms-ticket-empty">Your slip is empty. Add at least two different matches to generate a code.</div>';
  }
  function setResult(message, status, booking) {
    var host = drawer.querySelector('[data-ms-ticket-result]');
    if (!host) return;
    host.className = 'ms-ticket-result' + (status ? ' is-' + status : '');
    host.textContent = message || '';
    if (booking && booking.booking_code) {
      host.innerHTML = '<b>SportyBet code: <code>' + escapeHtml(booking.booking_code) + '</code></b>' +
        '<div class="ms-ticket-code-actions"><button type="button" data-ms-copy-code="' + escapeHtml(booking.booking_code) + '">Copy code</button><a href="' + escapeHtml(booking.share_url || ('https://www.sportybet.com/ng/?c=ng&shareCode=' + encodeURIComponent(booking.booking_code))) + '" target="_blank" rel="noopener">Open SportyBet ↗</a></div>' +
        '<small>' + escapeHtml(booking.selection_count || 0) + ' selections accepted' + (booking.combined_odds ? ' · revalidated combined odds ' + Number(booking.combined_odds).toFixed(3) + 'x' : '') + (booking.partial ? ' · partial code: inspect the validation response and final SportyBet slip' : '') + '</small>';
    }
  }
  async function loadManualFeed(force) {
    if (isBasketball || feedBusy) return;
    if (!force && feedFetchedAt && Date.now() - feedFetchedAt < 60000 && feedEvents.length) {
      renderFeedStatus(); return;
    }
    feedBusy = true; feedError = ''; renderFeedStatus(); renderSlip();
    var sportId = sport === 'football' ? 'sr:sport:1' : 'sr:sport:5';
    var marketIds = sport === 'football' ? '1,18,10,14,16,29,45,47' : '186,210,202,204,189,203,188,187';
    try {
      var pageRequests = [1, 2, 3].map(function (pageNum) {
        var url = './api/sportybet?sportId=' + encodeURIComponent(sportId) + '&marketId=' + encodeURIComponent(marketIds) + '&pageSize=100&pageNum=' + pageNum + '&timeline=168&_ms=' + Date.now();
        return fetch(url, { cache: 'no-store', headers: { 'Accept': 'application/json' } }).then(function (response) {
          if (!response.ok) throw new Error('SportyBet feed HTTP ' + response.status);
          return response.json();
        }).then(function (payload) {
          if (payload && payload.ok === false) throw new Error(payload.detail || payload.error || 'SportyBet feed unavailable');
          return payload && payload.data && Array.isArray(payload.data.tournaments) ? payload.data.tournaments : [];
        });
      });
      var pageResults = await Promise.allSettled(pageRequests);
      var tournaments = [], successfulPages = 0;
      pageResults.forEach(function (result) {
        if (result.status === 'fulfilled') {
          successfulPages++;
          tournaments = tournaments.concat(result.value);
        }
      });
      if (!successfulPages) throw new Error('All SportyBet fixture pages were unavailable.');
      var now = Date.now(), seen = {};
      feedEvents = [];
      tournaments.forEach(function (tournament) {
        (Array.isArray(tournament.events) ? tournament.events : []).forEach(function (raw) {
          var event = normalizeRawEvent(raw, tournament);
          if (!event.event_id || !event.home || !event.away || !event.start_time_ms || event.start_time_ms <= now + 120000) return;
          if (/live|running|playing|in.?play|started|finish|ended|final|completed|settled|closed|suspend/i.test(event.match_status)) return;
          if (seen[event.event_id] || optionsFor(event).length < 2) return;
          seen[event.event_id] = true; feedEvents.push(event);
        });
      });
      feedEvents.sort(function (a, b) { return a.start_time_ms - b.start_time_ms; });
      feedFetchedAt = Date.now();
      if (!feedEvents.length) feedError = 'No upcoming winner markets returned by the current feed. Refresh or open SportyBet to check availability.';
      renderFixtures();
      if (lastBooking) setResult('Last code is only a snapshot. Generate again to revalidate live prices.', 'warning');
    } catch (error) {
      feedError = 'Could not load SportyBet fixtures: ' + String(error && error.message || error);
      setResult(feedError, 'error');
    } finally {
      feedBusy = false; renderFeedStatus(); renderSlip();
    }
  }
  function addSelectedPick(pick, displayedOdds) {
    var event = selectedEvent();
    if (!event) return;
    var option = optionsFor(event).find(function (x) { return x.pick === pick; });
    if (!option || Math.abs(Number(displayedOdds) - option.odds) > 1e-6) {
      setResult('This price changed. Refresh the current SportyBet markets and select it again.', 'warning');
      return;
    }
    if (slip.some(function (item) { return item.event_id === event.event_id; })) {
      setResult('This fixture is already on the slip. Use a different match to avoid duplicate-event tickets.', 'warning');
      return;
    }
    if (slip.length >= 20) { setResult('SportyBet share codes are limited to 20 selections.', 'warning'); return; }
    var label = pick === 'p1' ? event.home : pick === 'p2' ? event.away : 'Draw';
    slip.push({
      event_id: event.event_id, sport: sport, market: 'winner', pick: pick,
      player_1: event.home, player_2: event.away, start_time: event.start_time,
      match: event.home + ' vs ' + event.away,
      display_pick: label, odds: option.odds
    });
    saveSlip(); lastBooking = null;
    setResult('Selection added. The price is rechecked by SportyBet when the code is generated.', 'success');
    renderSlip();
  }
  async function generateManualCode() {
    if (isBasketball) return;
    if (slip.length < 2 || slip.length > 20) return;
    var button = drawer.querySelector('[data-ms-ticket-generate]');
    if (button) { button.disabled = true; button.textContent = 'Rechecking and generating…'; }
    setResult('Revalidating every fixture and winner market with SportyBet…', 'loading');
    try {
      var manualSelections = slip.map(function (item) {
        return {
          event_id: item.event_id, sport: item.sport, market: item.market, pick: item.pick,
          player_1: item.player_1, player_2: item.player_2, start_time: item.start_time, match: item.match
        };
      });
      var response = await fetch('./api/sportybet-booking', {
        method: 'POST', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ mode: 'manual', manual_selections: manualSelections })
      });
      var payload = await response.json().catch(function () { return {}; });
      if (!response.ok || payload.ok !== true || !payload.booking_code) {
        var validation = Array.isArray(payload.validation) ? payload.validation : [];
        var reasons = validation.filter(function (x) { return x.ok !== true; }).map(function (x) { return String(x.reason || 'selection unavailable'); }).slice(0, 3);
        throw new Error(payload.message || payload.error || reasons.join('; ') || 'SportyBet did not return a booking code. No code was fabricated.');
      }
      lastBooking = payload;
      setResult('', 'success', payload);
    } catch (error) {
      setResult(String(error && error.message || error), 'error');
    } finally {
      if (button) { button.textContent = 'Generate SportyBet code'; button.disabled = slip.length < 2 || slip.length > 20; }
      renderSlip();
    }
  }
  function openDrawer() {
    previousFocus = document.activeElement;
    backdrop.hidden = false;
    drawer.hidden = false;
    document.documentElement.classList.add('ms-ticket-open');
    launcher.setAttribute('aria-expanded', 'true');
    if (isBasketball) {
      if (!loaded) { frame.src = builderUrl; loaded = true; }
    } else {
      loadManualFeed(false);
      renderSlip();
    }
    closeButton.focus();
  }
  function closeDrawer() {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.documentElement.classList.remove('ms-ticket-open');
    launcher.setAttribute('aria-expanded', 'false');
    if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
    else launcher.focus();
  }
  launcher.addEventListener('click', openDrawer);
  backdrop.addEventListener('click', closeDrawer);
  closeButton.addEventListener('click', closeDrawer);
  if (frame && frameWrap) frame.addEventListener('load', function () { frameWrap.setAttribute('data-loaded', 'true'); });

  drawer.addEventListener('change', function (event) {
    if (event.target && event.target.matches('[data-ms-ticket-fixture]')) renderOutcomes();
  });
  drawer.addEventListener('click', function (event) {
    var target = event.target.closest && event.target.closest('button');
    if (!target) return;
    if (target.hasAttribute('data-ms-feed-refresh')) { loadManualFeed(true); return; }
    if (target.hasAttribute('data-ms-add-pick')) {
      addSelectedPick(target.getAttribute('data-ms-add-pick'), target.getAttribute('data-ms-odds')); return;
    }
    if (target.hasAttribute('data-ms-remove-pick')) {
      var index = Number(target.getAttribute('data-ms-remove-pick'));
      if (Number.isInteger(index) && index >= 0 && index < slip.length) {
        slip.splice(index, 1); saveSlip(); lastBooking = null;
        setResult('Selection removed.', 'success'); renderSlip();
      }
      return;
    }
    if (target.hasAttribute('data-ms-ticket-clear')) {
      slip = []; saveSlip(); lastBooking = null;
      setResult('Slip cleared.', 'success'); renderSlip(); return;
    }
    if (target.hasAttribute('data-ms-ticket-generate')) { generateManualCode(); return; }
    if (target.hasAttribute('data-ms-copy-code')) {
      var code = target.getAttribute('data-ms-copy-code') || '';
      if (navigator.clipboard && code) navigator.clipboard.writeText(code).then(function () {
        target.textContent = 'Copied'; 
      }).catch(function () { setResult('Copy failed. Select the code text and copy it manually.', 'warning'); });
    }
  });
  document.addEventListener('keydown', function (event) {
    if (drawer.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault(); closeDrawer();
    } else if (event.key === 'Tab') {
      var focusable = Array.prototype.slice.call(drawer.querySelectorAll('button:not([disabled]),a[href],select'));
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  renderSlip();
})();
