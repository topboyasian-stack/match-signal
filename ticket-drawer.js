/* Shared floating ticket-box launcher for Match Signal sport desks. */
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
  var builderUrl = isBasketball
    ? './basketball.html?builderOnly=1&drawer=1#basketball-builders'
    : './odds-builder.html?embed=1&sport=' + encodeURIComponent(sport);
  var fullUrl = isBasketball ? './basketball.html#basketball-builders' : './odds-builder.html#builder-overview';
  var title = isBasketball ? 'Basketball ticket builders' : 'SportyBet ticket builder';
  var subtitle = isBasketball
    ? 'NBA totals · four builders · current release gate applies'
    : sport.charAt(0).toUpperCase() + sport.slice(1) + ' desk · shared evidence-gated builder';

  var launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.id = 'msTicketLauncher';
  launcher.className = 'ms-ticket-launcher';
  launcher.setAttribute('aria-haspopup', 'dialog');
  launcher.setAttribute('aria-controls', 'msTicketDrawer');
  launcher.setAttribute('aria-expanded', 'false');
  launcher.innerHTML = '<span class="ms-ticket-launcher-mark" aria-hidden="true">🎟</span><span class="ms-ticket-launcher-copy"><span>SportyBet Ticket Box</span><small>Tap to open builder</small></span>';

  var backdrop = document.createElement('button');
  backdrop.type = 'button';
  backdrop.className = 'ms-ticket-backdrop';
  backdrop.setAttribute('aria-label', 'Close SportyBet ticket builder');
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
      '<div class="ms-ticket-head-actions"><a class="ms-ticket-full-link" href="' + fullUrl + '" target="_blank" rel="noopener">Full page ↗</a><button type="button" class="ms-ticket-close" data-ticket-close aria-label="Close ticket builder">×</button></div>' +
    '</div>' +
    '<div class="ms-ticket-policy"><span class="ms-ticket-policy-icon" aria-hidden="true">●</span><span><b>Research only.</b> Codes use the existing SportyBet flow and must pass live checks. NBA code generation remains locked until its totals evidence qualifies; no wager is placed automatically.</span></div>' +
    '<div class="ms-ticket-frame-wrap"><div class="ms-ticket-frame-loading" role="status">Loading the existing Match Signal builder…</div><iframe class="ms-ticket-frame" title="' + escapeHtml(title) + '" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe></div>';

  document.body.appendChild(launcher);
  document.body.appendChild(backdrop);
  document.body.appendChild(drawer);
  var frame = drawer.querySelector('iframe');
  var frameWrap = drawer.querySelector('.ms-ticket-frame-wrap');
  var closeButton = drawer.querySelector('[data-ticket-close]');
  var loaded = false;
  var previousFocus = null;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }
  function openDrawer() {
    previousFocus = document.activeElement;
    backdrop.hidden = false;
    drawer.hidden = false;
    document.documentElement.classList.add('ms-ticket-open');
    launcher.setAttribute('aria-expanded', 'true');
    if (!loaded) {
      frame.src = builderUrl;
      loaded = true;
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
  frame.addEventListener('load', function () {
    frameWrap.setAttribute('data-loaded', 'true');
  });
  document.addEventListener('keydown', function (event) {
    if (drawer.hidden) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeDrawer();
    } else if (event.key === 'Tab') {
      var focusable = Array.prototype.slice.call(drawer.querySelectorAll('button:not([disabled]),a[href]'));
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
  });
})();
