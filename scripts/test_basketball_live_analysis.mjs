const assert = require("node:assert/strict");
const analysis = require("../basketball-live-analysis.js");

assert.equal(analysis.elapsedMinutes(2, "06:00"), 18);
assert.equal(analysis.elapsedMinutes(3, "06:00"), 30);
assert.equal(analysis.elapsedMinutes(5, "04:00"), 49);
assert.deepEqual(analysis.parsePair("7-22"), { made: 7, attempted: 22 });

const home = analysis.readTeamStats({
  statistics: [
    { name: "fieldGoalsMade-fieldGoalsAttempted", displayValue: "24-58" },
    { name: "threePointFieldGoalsMade-threePointFieldGoalsAttempted", displayValue: "7-22" },
    { name: "freeThrowsMade-freeThrowsAttempted", displayValue: "10-13" },
    { name: "offensiveRebounds", displayValue: "8" },
    { name: "totalRebounds", displayValue: "27" },
    { name: "turnovers", displayValue: "9" },
    { name: "assists", displayValue: "14" }
  ]
});
const away = analysis.readTeamStats({
  statistics: [
    { name: "fieldGoalsMade-fieldGoalsAttempted", displayValue: "23-57" },
    { name: "threePointFieldGoalsMade-threePointFieldGoalsAttempted", displayValue: "6-20" },
    { name: "freeThrowsMade-freeThrowsAttempted", displayValue: "8-11" },
    { name: "offensiveRebounds", displayValue: "7" },
    { name: "totalRebounds", displayValue: "25" },
    { name: "turnovers", displayValue: "10" },
    { name: "assists", displayValue: "12" }
  ]
});

assert.ok(Math.abs(home.possessions - (58 + 0.44 * 13 - 8 + 9)) < 0.001);
assert.equal(home.threePointMade, 7);
assert.equal(home.threePointAttempted, 22);

const estimate = analysis.projectLiveTotal({
  homeScore: 53,
  awayScore: 51,
  period: 3,
  clock: "06:00",
  baseline: 220,
  homeStats: home,
  awayStats: away
});
assert.equal(estimate.status, "LIVE_STATS_BASED");
assert.equal(estimate.elapsedMinutes, 30);
assert.ok(estimate.projectedTotal > 104);
assert.ok(estimate.projectedTotal < 220);
assert.ok(estimate.pacePer48 > 0);
assert.ok(estimate.pointsPerPossession > 0);
assert.equal(estimate.confidence, "MODERATE");

assert.equal(analysis.projectLiveTotal({
  homeScore: 53, awayScore: 51, period: 5, clock: "04:00", baseline: 220,
  homeStats: home, awayStats: away
}).status, "OVERTIME_NOT_PROJECTED");

assert.equal(analysis.projectLiveTotal({
  homeScore: 4, awayScore: 3, period: 1, clock: "08:00", baseline: 220,
  homeStats: home, awayStats: away
}).status, "WARMING_UP");

assert.equal(analysis.projectLiveTotal({
  homeScore: 53, awayScore: 51, period: 3, clock: "06:00", baseline: 220
}).status, "STATS_UNAVAILABLE");

assert.equal(analysis.projectLiveTotal({
  homeScore: 53, awayScore: 51, period: 3, clock: "06:00",
  homeStats: home, awayStats: away
}).status, "NO_PREGAME_BASELINE");

console.log("NBA live analysis model tests passed.");
