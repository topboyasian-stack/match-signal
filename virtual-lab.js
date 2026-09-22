/* Legacy compatibility shim. Production Virtual Lab uses virtual-lab-app.js only. */
(function(){
'use strict';
if(window.__MATCH_SIGNAL_VIRTUAL_LAB_APP__)return;
var src='/virtual-lab-app.js?v=VL-V1-20260922';
if(document.querySelector('script[src^="/virtual-lab-app.js"]'))return;
var s=document.createElement('script');
s.src=src;
s.defer=true;
(document.head||document.documentElement).appendChild(s);
})();
