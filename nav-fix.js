(() => {
  'use strict';
  const routes = {
    football: './index.html?sport=football',
    tennis: './index.html?sport=tennis',
    basketball: './basketball.html',
    performance: './performance.html'
  };

  function go(route) {
    const target = routes[route];
    if (target) window.location.href = target;
  }

  function install() {
    const links = document.querySelectorAll('.tabs a, .nav a');
    links.forEach(link => {
      if (link.dataset.msNavFix === '1') return;
      link.dataset.msNavFix = '1';
      link.addEventListener('click', event => {
        event.preventDefault();
        const href = link.getAttribute('href') || '';
        if (href.includes('sport=football')) return go('football');
        if (href.includes('sport=tennis')) return go('tennis');
        if (href.includes('basketball')) return go('basketball');
        if (href.includes('performance')) return go('performance');
        go('football');
      }, true);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
