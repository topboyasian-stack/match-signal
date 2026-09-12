(() => {
  'use strict';
  async function apply() {
    const sport = new URLSearchParams(location.search).get('sport') === 'tennis' ? 'tennis' : 'football';
    try {
      const [ar, hr] = await Promise.all([
        fetch('./data/accuracy.json?metrics=' + Date.now(), {cache:'no-store'}),
        fetch('./data/prediction_history.json?metrics=' + Date.now(), {cache:'no-store'})
      ]);
      if (!ar.ok || !hr.ok) return;
      const d = await ar.json();
      const history = await hr.json();
      const s = (d.summary || {})[sport] || {};
      const rows = (Array.isArray(history) ? history : []).filter(x => String(x.sport || '').toLowerCase() === sport && x.settled);
      const brier = rows.length ? rows.reduce((a,p) => a + Number(p.brier || 0), 0) / rows.length : null;
      document.getElementById('accuracy').textContent = rows.length ? ((Number(s.accuracy || 0) * 100).toFixed(1) + '%') : '—';
      document.getElementById('settled').textContent = String(s.settled || 0);
      document.getElementById('brier').textContent = brier == null ? '—' : brier.toFixed(3);
    } catch (e) { console.warn('sport metrics fix failed', e); }
  }
  document.addEventListener('DOMContentLoaded', apply);
  setTimeout(apply, 1500);
  setTimeout(apply, 4000);
})();
