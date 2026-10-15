# Evidence bar (fixed in advance)

PAPER ONLY. These thresholds are written before looking at more results and are not to be changed to
make the model pass. Check status with `python scripts/evidence_bar_check.py`.

The model's eFootball single picks count as having a demonstrated edge only when ALL of these hold,
measured at the odds frozen when the pick was made:

1. At least 1,000 settled single picks.
2. ROI 95% range entirely above zero.
3. ROI positive in both the first and second chronological halves.
4. Overall stated probability within 2 points of the actual hit rate.
5. Every 10-point probability bucket with at least 30 picks within 5 points of its hit rate.
6. Settlement coverage of at least 70% of forecast fixture-lines, so the record is not a biased subset.

Accumulator tickets are not evidence for the model: they reuse legs, so results are not independent.

Rules while the test runs: do not change the model or its qualification gate mid-test; if you do, restart
the count from the change date. One editor at a time on the model files (human or assistant).
