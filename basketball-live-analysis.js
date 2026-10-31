(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MatchSignalBasketballLiveAnalysis = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function normalized(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  }

  function parsePair(value) {
    const match = String(value == null ? "" : value).match(/(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)/);
    return match ? { made: Number(match[1]), attempted: Number(match[2]) } : null;
  }

  function findStat(stats, patterns) {
    return stats.find(function (stat) {
      const name = normalized(stat && (stat.name || stat.abbreviation || stat.label || stat.displayName));
      return patterns.some(function (pattern) { return name.includes(pattern); });
    }) || null;
  }

  function statNumber(stat, pairPart) {
    if (!stat) return null;
    const value = stat.displayValue != null ? stat.displayValue : stat.value;
    const pair = parsePair(value);
    if (pair) return pairPart === "made" ? pair.made : pair.attempted;
    return finite(String(value == null ? "" : value).replace(/,/g, ""));
  }

  function readTeamStats(team) {
    if (!team || typeof team !== "object") return null;
    const stats = Array.isArray(team.statistics) ? team.statistics :
      Array.isArray(team.stats) ? team.stats : [];
    if (!stats.length) return null;

    const fg = findStat(stats, ["fieldgoalsmadefieldgoalsattempted", "fieldgoalsattempted", "fga"]);
    const threes = findStat(stats, ["threepointfieldgoalsmade", "threepointfieldgoalsattempted", "threepointersmade", "3pt"]);
    const freeThrows = findStat(stats, ["freethrowsmade", "freethrowsattempted", "fta"]);
    const fga = statNumber(fg, "attempted");
    const fta = statNumber(freeThrows, "attempted");
    const threePointMade = statNumber(threes, "made");
    const threePointAttempted = statNumber(threes, "attempted");
    const offensiveRebounds = statNumber(findStat(stats, ["offensiverebounds", "oreb"]), null);
    const totalRebounds = statNumber(findStat(stats, ["totalrebounds", "rebounds", "reb"]), null);
    const turnovers = statNumber(findStat(stats, ["turnovers", "tov"]), null);
    const assists = statNumber(findStat(stats, ["assists", "ast"]), null);
    const steals = statNumber(findStat(stats, ["steals", "stl"]), null);
    const blocks = statNumber(findStat(stats, ["blocks", "blk"]), null);

    const possessions = [fga, fta, offensiveRebounds, turnovers].every(Number.isFinite)
      ? Math.max(0, fga + 0.44 * fta - offensiveRebounds + turnovers)
      : null;

    return {
      fga: fga,
      fta: fta,
      threePointMade: threePointMade,
      threePointAttempted: threePointAttempted,
      offensiveRebounds: offensiveRebounds,
      totalRebounds: totalRebounds,
      turnovers: turnovers,
      assists: assists,
      steals: steals,
      blocks: blocks,
      possessions: possessions
    };
  }

  function clockSeconds(clock) {
    const match = String(clock == null ? "" : clock).trim().match(/^(\d{1,2}):(\d{1,2})$/);
    if (!match) return null;
    const minutes = Number(match[1]);
    const seconds = Number(match[2]);
    if (seconds > 59) return null;
    return minutes * 60 + seconds;
  }

  function elapsedMinutes(period, clock) {
    const p = finite(period);
    const remaining = clockSeconds(clock);
    if (p == null || p < 1 || remaining == null) return null;
    const quarterLength = p <= 4 ? 12 : 5;
    if (remaining > quarterLength * 60) return null;
    if (p <= 4) return (p - 1) * 12 + (12 - remaining / 60);
    return 48 + (p - 5) * 5 + (5 - remaining / 60);
  }

  function rounded(value, digits) {
    const factor = Math.pow(10, digits || 0);
    return Math.round(value * factor) / factor;
  }

  function projectLiveTotal(input) {
    const data = input || {};
    const homeScore = finite(data.homeScore);
    const awayScore = finite(data.awayScore);
    const currentTotal = homeScore == null || awayScore == null ? null : homeScore + awayScore;
    const period = finite(data.period);
    const baseline = finite(data.baseline);
    const elapsed = elapsedMinutes(period, data.clock);

    if (data.completed) return { status: "FINAL", currentTotal: currentTotal };
    if (period != null && period > 4) {
      return { status: "OVERTIME_NOT_PROJECTED", currentTotal: currentTotal, reason: "Overtime is excluded from this regulation-pace estimate." };
    }
    if (currentTotal == null || elapsed == null) {
      return { status: "CLOCK_OR_SCORE_UNAVAILABLE", currentTotal: currentTotal };
    }
    if (elapsed < 5) {
      return { status: "WARMING_UP", currentTotal: currentTotal, elapsedMinutes: rounded(elapsed, 1) };
    }
    if (baseline == null || baseline < 100 || baseline > 300) {
      return { status: "NO_PREGAME_BASELINE", currentTotal: currentTotal, elapsedMinutes: rounded(elapsed, 1) };
    }

    const home = data.homeStats || null;
    const away = data.awayStats || null;
    if (!home || !away || !Number.isFinite(home.possessions) || !Number.isFinite(away.possessions)) {
      return { status: "STATS_UNAVAILABLE", currentTotal: currentTotal, baseline: baseline, elapsedMinutes: rounded(elapsed, 1) };
    }

    const averagePossessions = (home.possessions + away.possessions) / 2;
    const combinedPossessions = home.possessions + away.possessions;
    if (averagePossessions < 5 || combinedPossessions <= 0) {
      return { status: "INSUFFICIENT_POSSESSION_SAMPLE", currentTotal: currentTotal, baseline: baseline, elapsedMinutes: rounded(elapsed, 1) };
    }

    const pacePer48 = averagePossessions / elapsed * 48;
    const pointsPerPossession = currentTotal / combinedPossessions;
    const livePaceProjection = 2 * pacePer48 * pointsPerPossession;
    const liveWeight = Math.min(0.8, Math.max(0.15, elapsed / 48));
    const projectedTotal = baseline * (1 - liveWeight) + livePaceProjection * liveWeight;
    const confidence = elapsed >= 24 && averagePossessions >= 40 ? "MODERATE" :
      elapsed >= 12 && averagePossessions >= 20 ? "LOW" : "EARLY";

    return {
      status: "LIVE_STATS_BASED",
      elapsedMinutes: rounded(elapsed, 1),
      currentTotal: currentTotal,
      baseline: baseline,
      projectedTotal: rounded(projectedTotal, 1),
      livePaceProjection: rounded(livePaceProjection, 1),
      adjustment: rounded(projectedTotal - baseline, 1),
      pacePer48: rounded(pacePer48, 1),
      pointsPerPossession: rounded(pointsPerPossession, 3),
      liveWeight: rounded(liveWeight, 3),
      confidence: confidence,
      homePossessions: rounded(home.possessions, 1),
      awayPossessions: rounded(away.possessions, 1)
    };
  }

  return {
    parsePair: parsePair,
    readTeamStats: readTeamStats,
    elapsedMinutes: elapsedMinutes,
    projectLiveTotal: projectLiveTotal
  };
});
