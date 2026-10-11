#!/usr/bin/env python3
"""Offline regression tests for permanent licensed club-logo discovery."""
import unittest

from scripts.sync_club_logos import (
    ALIASES,
    _candidate_title_matches,
    _existing_entry_is_safe,
    _signature_ok,
    is_football_product,
    license_allowed,
    normalize_team,
    split_fixture,
)


class ClubLogoRegistryTests(unittest.TestCase):
    def test_normalization_removes_game_handle_and_fc_suffix(self):
        self.assertEqual(normalize_team("Liverpool FC (v1nniePuh)"), "liverpool")
        self.assertEqual(normalize_team("AFC Bournemouth"), "bournemouth")
        self.assertEqual(normalize_team("Paris Saint-Germain"), "paris saint germain")

    def test_fixture_split_returns_club_names_without_player_handles(self):
        self.assertEqual(
            split_fixture("Liverpool (PlayerOne) vs Tottenham (PlayerTwo)"),
            ("Liverpool", "Tottenham"),
        )
        self.assertEqual(split_fixture("Liverpool vs"), ())

    def test_efootball_and_regular_football_are_scanned_but_tennis_is_not(self):
        self.assertTrue(is_football_product("efootball_gt"))
        self.assertTrue(is_football_product("efootball_adriatic"))
        self.assertTrue(is_football_product("football"))
        self.assertFalse(is_football_product("tennis"))

    def test_license_allowlist_accepts_attribution_licenses_only(self):
        self.assertTrue(license_allowed("CC BY 4.0"))
        self.assertTrue(license_allowed("CC BY-SA 4.0"))
        self.assertTrue(license_allowed("CC BY-SA 3.0 Unported"))
        self.assertTrue(license_allowed("CC BY 2.0 Generic"))
        self.assertTrue(license_allowed("Public domain"))
        self.assertTrue(license_allowed("CC0 1.0"))
        self.assertFalse(license_allowed("CC BY-NC-SA 4.0"))
        self.assertFalse(license_allowed("All rights reserved"))

    def test_common_provider_names_have_verified_search_aliases(self):
        self.assertIn("Liverpool FC", ALIASES["liverpool"])
        self.assertIn("Manchester City FC", ALIASES["man city"])
        self.assertIn("FC Barcelona", ALIASES["barcelona"])
        self.assertIn("Tottenham Hotspur FC", ALIASES["spurs"])

    def test_logo_candidates_must_be_current_and_club_specific(self):
        self.assertTrue(_candidate_title_matches("Boca Juniors", "Club Atletico Boca Juniors logo (70 stars).png"))
        self.assertTrue(_candidate_title_matches("Belgium", "Belgium football lion crest.png"))
        self.assertFalse(_candidate_title_matches("Athletic Club", "Seattle Athletic Club logo emblem.jpg"))
        self.assertFalse(_candidate_title_matches("Racing Club", "Logo Racing Club Vichy Rugby RCV.gif"))
        self.assertFalse(_candidate_title_matches("Wolves", "New York Wolves Supporters Club Pin Badge.jpg"))
        self.assertFalse(_candidate_title_matches("Liverpool FC", "Liverpool FC crest, Main Stand - side view.jpg"))
        self.assertFalse(_candidate_title_matches("Arsenal", "Arsenal FC old crest small.png"))
        self.assertFalse(_candidate_title_matches("Barcelona", "FC Barcelona original crest (1899-1910).png"))

    def test_old_or_wrong_registry_entry_is_not_reused_forever(self):
        bad = {
            "name": "Athletic Club",
            "title": "File:Seattle Athletic Club logo emblem.jpg",
            "path": "/assets/club-logos/athletic-club.jpg",
        }
        self.assertFalse(_existing_entry_is_safe("athletic club", bad))
        good = {
            "name": "Boca Juniors",
            "title": "File:Club Atlético Boca Juniors logo (70 stars).png",
            "path": "/assets/club-logos/boca-juniors.png",
        }
        self.assertTrue(_existing_entry_is_safe("boca juniors", good))

    def test_downloaded_image_signature_is_checked(self):
        self.assertTrue(_signature_ok(b"\x89PNG\r\n\x1a\n" + b"x" * 10, "image/png"))
        self.assertTrue(_signature_ok(b"\xff\xd8\xff" + b"x" * 10, "image/jpeg"))
        self.assertFalse(_signature_ok(b"not an image", "image/png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
