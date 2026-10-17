from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = (ROOT / ".github/workflows/automation_watchdog.yml").read_text(encoding="utf-8")
RESEARCH = (ROOT / ".github/workflows/efootball-market-research-schedule.yml").read_text(encoding="utf-8")


class EfootballResearchRecoveryTests(unittest.TestCase):
    def test_research_workflow_is_monitored_separately(self):
        self.assertIn("Isolated eFootball Winner and BTTS Market Research", WATCHDOG)
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

    def test_watchdog_contract_is_run_by_research_pr_validation(self):
        self.assertIn("scripts/test_automation_watchdog_research_recovery.py", RESEARCH)
        self.assertIn("python scripts/test_automation_watchdog_research_recovery.py", RESEARCH)


if __name__ == "__main__":
    unittest.main(verbosity=2)
