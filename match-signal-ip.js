/* Match Signal IP & Provenance Layer
 * Public owner identity: Diddy
 * Copyright © 2026 Diddy. All rights reserved.
 * Build marker: MS-V6-IP-2026.09.21
 */
(function () {
  "use strict";

  const BRAND = "MATCH SIGNAL";
  const OWNER = "Diddy";
  const COPYRIGHT = "© 2026 Diddy. All rights reserved.";
  const BUILD = "MS-V6-IP-2026.09.21";
  const OFFICIAL = "match-signal.pages.dev";

  function installStyles() {
    if (document.getElementById("ms-ip-style")) return;
    const style = document.createElement("style");
    style.id = "ms-ip-style";
    style.textContent = `
      .ms-ip-footer{margin:34px auto 20px;max-width:1180px;padding:14px 18px;border-top:1px solid rgba(89,215,255,.22);display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#9eb0bf;font:600 11px/1.5 system-ui,-apple-system,sans-serif;letter-spacing:.05em;text-transform:uppercase}
      .ms-ip-footer strong{color:#d9f7ff;letter-spacing:.12em}
      .ms-ip-footer .ms-ip-owner{color:#65e6bd}
      .ms-ip-footer .ms-ip-build{opacity:.72}
      .ms-ip-about{border:1px solid rgba(89,215,255,.28);background:rgba(16,28,39,.94);color:#dce9f2;border-radius:10px;padding:7px 10px;font:700 11px system-ui;cursor:pointer}
      .ms-ip-about:hover{border-color:#59d7ff;box-shadow:0 0 18px rgba(89,215,255,.12)}
      .ms-ip-modal{position:fixed;inset:0;z-index:2147483000;background:rgba(3,7,11,.78);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:20px}
      .ms-ip-modal.is-open{display:flex}
      .ms-ip-dialog{width:min(560px,100%);background:linear-gradient(145deg,#172330,#0e1822);border:1px solid rgba(89,215,255,.32);border-radius:16px;box-shadow:0 24px 80px rgba(0,0,0,.55);padding:24px;color:#dce9f2}
      .ms-ip-dialog h2{margin:0 0 6px;font:800 22px system-ui;letter-spacing:.08em}
      .ms-ip-dialog .ms-ip-sub{color:#65e6bd;font-weight:800;letter-spacing:.1em;font-size:11px}
      .ms-ip-dialog p{color:#aebdca;line-height:1.65}
      .ms-ip-dialog code{color:#79e8ff}
      .ms-ip-close{float:right;border:0;background:transparent;color:#aebdca;font-size:22px;cursor:pointer}
      .ms-ip-print-watermark{display:none}
      @media print{
        .ms-ip-footer{color:#222;border-top:1px solid #bbb}
        .ms-ip-footer strong,.ms-ip-footer .ms-ip-owner{color:#111}
        .ms-ip-about,.ms-ip-modal{display:none!important}
        .ms-ip-print-watermark{display:block;position:fixed;inset:0;z-index:999999;pointer-events:none;opacity:.055;transform:rotate(-24deg);font:900 28px/1.4 Arial,sans-serif;letter-spacing:.12em;color:#111;word-break:break-all;padding:18vh 5vw}
      }
    `;
    document.head.appendChild(style);
  }

  function install() {
    installStyles();
    if (!document.querySelector(".ms-ip-footer")) {
      const footer = document.createElement("footer");
      footer.className = "ms-ip-footer";
      footer.innerHTML = `
        <span><strong>${BRAND}</strong> <span class="ms-ip-owner">• Public owner: ${OWNER}</span></span>
        <span>${COPYRIGHT}</span>
        <span class="ms-ip-build">Build ${BUILD}</span>
        <button class="ms-ip-about" type="button" aria-label="About Match Signal ownership">ⓘ Ownership</button>
      `;
      document.body.appendChild(footer);
    }

    if (!document.querySelector(".ms-ip-print-watermark")) {
      const wm = document.createElement("div");
      wm.className = "ms-ip-print-watermark";
      wm.textContent = (BRAND + " • " + OWNER + " • " + COPYRIGHT + " • " + BUILD + " • " + OFFICIAL + " • ").repeat(8);
      document.body.appendChild(wm);
    }

    if (!document.querySelector(".ms-ip-modal")) {
      const modal = document.createElement("div");
      modal.className = "ms-ip-modal";
      modal.innerHTML = `
        <div class="ms-ip-dialog" role="dialog" aria-modal="true" aria-label="Match Signal ownership">
          <button class="ms-ip-close" type="button" aria-label="Close">×</button>
          <div class="ms-ip-sub">OFFICIAL PROVENANCE</div>
          <h2>${BRAND}</h2>
          <p><strong>Public owner identity:</strong> ${OWNER}</p>
          <p>${COPYRIGHT}</p>
          <p><strong>Build:</strong> <code>${BUILD}</code></p>
          <p><strong>Official production:</strong> <code>https://${OFFICIAL}</code></p>
          <p>Match Signal is proprietary software. Public viewing does not grant permission to reproduce, rebrand, impersonate, redistribute, or commercially exploit the proprietary implementation.</p>
        </div>`;
      document.body.appendChild(modal);
      const close = () => modal.classList.remove("is-open");
      modal.addEventListener("click", e => { if (e.target === modal || e.target.closest(".ms-ip-close")) close(); });
      document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
      document.querySelector(".ms-ip-about").addEventListener("click", () => modal.classList.add("is-open"));
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();