"""Regression tests for replaying alternate eFootball O/U half-lines from settled scores."""

import odds_builder as builder


def archive_row(event_id, total, *, product="efootball_gt", stamp="2026-10-01T00:00:00+00:00"):
    return {
        "product": product,
        "event_id": event_id,
        "market": "ou",
        "line": 6.5,
        "selection": "O6.5",
        "win": total > 6.5,
        "score": f"{total}:0",
        "settled_at": stamp,
        "timestamp": stamp,
    }


def event_rows(totals, *, repeats=1, product="efootball_gt"):
    rows = []
    for i, total in enumerate(totals, 1):
        for repeat in range(repeats):
            rows.append(archive_row(
                f"{product}-event-{i}",
                total,
                product=product,
                stamp=f"2026-10-{min(i, 9):02d}T{repeat:02d}:00:00+00:00",
            ))
    return rows


def test_reconstructs_both_sides_from_final_scores():
    rows = event_rows(range(1, 11))
    derived, diag = builder._derive_efootball_score_replay(rows, {})

    over = derived[("efootball_gt", "1.5", "over")]
    under = derived[("efootball_gt", "1.5", "under")]
    assert len(over) == len(under) == 10
    assert sum(row["win"] is True for row in over) == 9
    assert sum(row["win"] is True for row in under) == 1
    assert all(row["derived_from_score"] is True for row in over + under)
    assert len({row["event_id"] for row in over}) == 10
    assert diag["unique_score_events"] == 10
    assert diag["min_direct_observations_before_replay"] == 8


def test_repeated_lines_for_the_same_event_count_once():
    rows = event_rows(range(1, 11), repeats=5)
    derived, diag = builder._derive_efootball_score_replay(rows, {})

    over = derived[("efootball_gt", "1.5", "over")]
    assert len(rows) == 50
    assert len(over) == 10
    assert len({row["event_id"] for row in over}) == 10
    assert diag["unique_score_events"] == 10


def test_conflicting_scores_are_excluded_instead_of_guessed():
    rows = event_rows(range(1, 10))
    rows.append({
        **archive_row(
            "efootball_gt-event-1",
            30,
            stamp="2026-10-10T00:00:00+00:00",
        )
    })
    derived, diag = builder._derive_efootball_score_replay(rows, {})

    over = derived[("efootball_gt", "1.5", "over")]
    assert len(over) == 8
    assert "efootball_gt-event-1" not in {row["event_id"] for row in over}
    assert diag["conflicting_score_events_skipped"] == 1


def test_eight_direct_observations_keep_priority_over_replay():
    direct = {
        ("efootball_gt", "1.5", "over"): [{"win": True} for _ in range(8)]
    }
    derived, _ = builder._derive_efootball_score_replay(event_rows(range(1, 11)), direct)

    assert ("efootball_gt", "1.5", "over") not in derived
    assert ("efootball_gt", "1.5", "under") in derived


def test_score_replay_is_efootball_only():
    derived, diag = builder._derive_efootball_score_replay(
        event_rows(range(1, 11), product="vfootball"),
        {},
    )
    assert derived == {}
    assert diag["unique_score_events"] == 0


def test_integer_lines_are_not_replayed_without_push_accounting():
    derived, _ = builder._derive_efootball_score_replay(event_rows(range(1, 11)), {})
    assert ("efootball_gt", "3", "over") not in derived
    assert ("efootball_gt", "3", "under") not in derived


def test_builder_ui_labels_score_replay_and_still_displays_exact_quote():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "expansion-odds-builder.js"
    ui = source.read_text(encoding="utf-8")
    assert "Settled-score replay" in ui
    assert "Evidence basis" in ui
    assert "viewLeg.bookmaker_odds" in ui
    # Provenance must survive make_leg() serialization into the Builder artifact.
    odds_builder_source = Path(__file__).resolve().parent / "odds_builder.py"
    python_code = odds_builder_source.read_text(encoding="utf-8")
    assert '"evidence_source":x.get("evidence_source")' in python_code
    assert '"score_derived_evidence":bool(x.get("score_derived_evidence"))' in python_code
    assert '"evidence_sample_n":int(x.get("evidence_sample_n") or 0)' in python_code
    # The live quote join must still use an exact numeric line, never another rung.
    assert "abs(float(m.get(\"line\"))-float(line))<1e-9" in python_code


if __name__ == "__main__":
    test_reconstructs_both_sides_from_final_scores()
    test_repeated_lines_for_the_same_event_count_once()
    test_conflicting_scores_are_excluded_instead_of_guessed()
    test_eight_direct_observations_keep_priority_over_replay()
    test_score_replay_is_efootball_only()
    test_integer_lines_are_not_replayed_without_push_accounting()
    test_builder_ui_labels_score_replay_and_still_displays_exact_quote()
    print("eFootball settled-score O/U line replay regression checks: PASS")
