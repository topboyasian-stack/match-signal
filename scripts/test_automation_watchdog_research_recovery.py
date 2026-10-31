from pathlib import Path
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "scripts"))
from system_health_audit_lib import nba_live_observation_health_summary, virtual_live_health_summary
WATCHDOG = (ROOT / ".github/workflows/automation_watchdog.yml").read_text(encoding="utf-8")
RESEARCH = (ROOT / ".github/workflows/efootball-market-research-schedule.yml").read_text(encoding="utf-8")
PAGES = (ROOT / ".github/workflows/cloudflare-pages.yml").read_text(encoding="utf-8")


class EfootballResearchRecoveryTests(unittest.TestCase):
    def test_virtual_live_source_cannot_be_marked_fresh_by_downstream_refresh(self):
        check, issues = virtual_live_health_summary(
            {"status": "LIVE", "events_count": 20}, 4.0
        )
        self.assertEqual(check["status"], "STALE")
        self.assertEqual(issues[0]["code"], "VIRTUAL_LIVE_FEED_STALE")

    def test_nba_observation_recorder_staleness_is_visible(self):
        check, issues = nba_live_observation_health_summary(
            {"games": {}}, 1.0
        )
        self.assertEqual(check["status"], "STALE")
        self.assertEqual(issues[0]["code"], "NBA_LIVE_OBSERVATION_STALE")

    def test_schedules_are_registered_on_staggered_offset_cadences(self):
        self.assertIn("cron: '8,18,28,38,48,58 * * * *'", WATCHDOG)
        self.assertIn("cron: '5,15,25,35,45,55 * * * *'", (ROOT / ".github/workflows/qualified-best-health-watch-v2.yml").read_text(encoding="utf-8"))
        self.assertIn("cron: '9,24,39,54 * * * *'", RESEARCH)

    def test_research_workflow_is_monitored_separately(self):
        self.assertIn("Isolated eFootball Winner and BTTS Market Research", WATCHDOG)
        self.assertIn('"Match Signal Virtual Lab Collector"', RESEARCH,
                      "Refresh performance reports after the collector publishes a new chronological model evaluation")
        self.assertIn("github.event.workflow_run.conclusion == 'success'", RESEARCH,
                      "Only process the new model evaluation after a successful collector run")
        self.assertIn("efootball_market_archive_age_minutes", WATCHDOG)
        self.assertIn("efootball_collector_age_minutes", WATCHDOG)
        self.assertIn("EFOOTBALL_RESEARCH_MAX_AGE_MINUTES = 30", WATCHDOG)
        self.assertIn("EFOOTBALL_RESEARCH_DISPATCH_COOLDOWN_MINUTES = 15", WATCHDOG)
        self.assertIn("MISSING_SCHEDULED_RUN", WATCHDOG)
        self.assertIn("efootball_research_schedule_fallback_needed", WATCHDOG)
        self.assertIn("efootball_research_scheduled_age_minutes", WATCHDOG)
        self.assertIn("efootball_research_last_success_age_minutes", WATCHDOG)
        self.assertIn("suppressed_recent_success", WATCHDOG)
        self.assertIn("efootball_market_research_freshness_status", WATCHDOG)

    def test_odds_builder_stale_recovery_matches_15_minute_cadence(self):
        self.assertIn("ODDS_BUILDER_MAX_AGE_MINUTES = 25", WATCHDOG)
        self.assertIn("if odds_age_minutes > ODDS_BUILDER_MAX_AGE_MINUTES and not active('odds_builder.yml'):", WATCHDOG)
        self.assertNotIn("if odds_age > 8 and not active('odds_builder.yml'):", WATCHDOG)
        self.assertIn("'odds_builder_age_minutes': odds_age_minutes", WATCHDOG)

    def test_stale_virtual_and_nba_live_sources_have_bounded_recovery(self):
        self.assertIn('"Match Signal Odds Builder"', WATCHDOG)
        self.assertIn('"Match Signal NBA In-Game Behavior Recorder"', WATCHDOG)
        self.assertIn("VIRTUAL_LIVE_MAX_AGE_MINUTES = 30", WATCHDOG)
        self.assertIn("NBA_LIVE_MAX_AGE_MINUTES = 15", WATCHDOG)
        self.assertIn("LIVE_FEED_DISPATCH_COOLDOWN_MINUTES = 10", WATCHDOG)
        self.assertIn("virtual-lab-live-sync-heartbeat.yml", WATCHDOG)
        self.assertIn("nba-live-observation.yml", WATCHDOG)
        self.assertIn("python scripts/system_health_audit.py", WATCHDOG)

    def test_automation_watchdog_changes_do_not_trigger_a_static_pages_deploy(self):
        self.assertNotIn(
            "      - '.github/workflows/automation_watchdog.yml'",
            PAGES,
            "watchdog-only changes must not consume a Cloudflare Pages production deployment",
        )

    def test_watchdog_contract_is_run_by_research_pr_validation(self):
        self.assertIn("scripts/test_automation_watchdog_research_recovery.py", RESEARCH)
        self.assertIn("python scripts/test_automation_watchdog_research_recovery.py", RESEARCH)

    def test_inline_watchdog_recovery_script_is_valid_python(self):
        marker = "          python - <<'PY'"
        start = WATCHDOG.index(marker) + len(marker)
        start = WATCHDOG.index(chr(10), start) + 1
        end = WATCHDOG.index("          PY", start)
        script = textwrap.dedent(WATCHDOG[start:end])
        compile(script, "automation_watchdog_inline.py", "exec")


if __name__ == "__main__":
    unittest.main(verbosity=2)
