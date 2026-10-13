/* Competition-level logos for the Football competition cards.
 * Source: API-FOOTBALL public league image CDN. IDs are explicit, reviewed aliases;
 * unknown competitions deliberately do not get a possibly incorrect logo.
 */
(function installCompetitionLogos(root) {
  "use strict";

  const LEAGUE_NAMES = Object.freeze({
    "premier league": 39,
    "english premier league": 39,
    "england premier league": 39,
    epl: 39,
    "la liga": 140,
    laliga: 140,
    "spanish la liga": 140,
    bundesliga: 78,
    "german bundesliga": 78,
    "ligue 1": 61,
    "french ligue 1": 61,
    "champions league": 2,
    "uefa champions league": 2,
    "serie a": 135,
    "italian serie a": 135,
    mls: 253,
    "major league soccer": 253,
    "primeira liga": 94,
    "liga portugal": 94,
    "portuguese primeira liga": 94,
    "england amateur u21 professional development league": 614,
    "england u21 professional development league": 614,
    "professional development league": 614,
    "saudi pro league": 307,
    "saudi professional league": 307,
    "eredivisie": 88,
    "dutch eredivisie": 88,
    "turkish super lig": 203,
    "scottish premiership": 179,
    "europa league": 3,
    "uefa europa league": 3,
    "conference league": 848,
    "uefa conference league": 848,
    "copa libertadores": 13,
    "afc champions league": 17,
    "premier league 2": 593,
    "fa cup": 45,
    "england fa cup": 45,
    "efl cup": 48,
    "league cup": 48,
    "carabao cup": 48
  });

  function normalizeCompetitionName(name) {
    return String(name || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim()
      .replace(/\s+/g, " ");
  }

  function logoIdForCompetition(name) {
    return LEAGUE_NAMES[normalizeCompetitionName(name)] || null;
  }

  function logoUrlForCompetition(name) {
    const id = logoIdForCompetition(name);
    return id ? "https://media.api-sports.io/football/leagues/" + id + ".png" : null;
  }

  function enhanceCards(grid) {
    if (!grid || !grid.querySelectorAll) return;
    grid.querySelectorAll(".ms-league").forEach(function (card) {
      if (card.dataset.competitionLogoApplied === "true") return;
      const header = card.querySelector(".ms-league-top");
      const title = header && header.querySelector("h3");
      if (!header || !title) return;
      const name = title.textContent.trim();
      const url = logoUrlForCompetition(name);

      if (!url) {
        // Do not substitute a different league's badge when an alias is unknown.
        card.dataset.competitionLogoApplied = "unmapped";
        return;
      }

      const img = document.createElement("img");
      img.className = "ms-competition-logo";
      img.alt = name + " competition logo";
      img.title = name;
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      img.src = url;
      img.addEventListener("error", function () {
        // Keep the league name visible and remove broken-image chrome.
        img.remove();
      }, { once: true });
      header.insertBefore(img, title);
      card.dataset.competitionLogoApplied = "true";
    });
  }

  root.MatchSignalLeagueLogos = Object.freeze({
    logoIdForCompetition: logoIdForCompetition,
    logoUrlForCompetition: logoUrlForCompetition,
    normalizeCompetitionName: normalizeCompetitionName
  });

  function boot() {
    const grid = document.querySelector("#leagueGrid");
    if (!grid) return;
    enhanceCards(grid);
    const observer = new MutationObserver(function () { enhanceCards(grid); });
    observer.observe(grid, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})(window);
