#!/usr/bin/env python3
"""Offline regression tests for permanent licensed club-logo discovery."""
import unittest

from scripts.sync_club_logos import (
    ALIASES,
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

    def test_downloaded_image_signature_is_checked(self):
        self.assertTrue(_signature_ok(b"\x89PNG\r\n\x1a\n" + b"x" * 10, "image/png"))
        self.assertTrue(_signature_ok(b"\xff\xd8\xff" + b"x" * 10, "image/jpeg"))
        self.assertFalse(_signature_ok(b"not an image", "image/png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
