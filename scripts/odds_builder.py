MIN_LEGS,MAX_LEGS=1,7
# Fixed minimum accumulator policy: every published paper batch must reach 4.00x.
# Leg count remains adaptive: 2–7 legs are available, but no weak leg is added just
# to reach the odds target. Results-first/model/evidence/ROI gates remain intact.
TARGET_COMBINED_ODDS=4.0
STRETCH_COMBINED_ODDS=4.0
MIN_ACCURACY_FIRST_ODDS=4.0
ACCURACY_PRESERVATION_RATIO=0.90
BATCH_MIN_LEGS=2
# Adaptive 2–7 leg construction safety tiers.
# 90%+ per-leg model probability is preferred; 80% is the safety floor for every
# included leg regardless of whether the ticket has 2 through 7 legs.
LEG_COUNT_MIN_MODEL_PROBABILITY={2:0.80,3:0.80,4:0.80,5:0.80,6:0.80,7:0.80}
MIN_SAFE_LEG_MODEL_PROBABILITY=0.80
PREFERRED_LEG_MODEL_PROBABILITY=0.90
HIGH_ODDS_TARGET=4.0
HIGH_ODDS_HARD_GATE_WIN_RECORDS=0
# Results-first Builder: 4.00 minimum combined odds is now a fixed eligibility floor.
# A weak extra leg is never added merely to reach 4.00.
RESULTS_FIRST_ENABLED=True
RESULTS_FIRST_MAX_LEGS=7
RESULTS_FIRST_MIN_OBS=50
RESULTS_FIRST_MIN_ACCURACY=0.90
RESULTS_FIRST_MIN_COMBINED_ODDS=4.0
# Existing Results-first expected-ROI floor used by construction diagnostics and QA.
RESULTS_FIRST_MIN_EXPECTED_ROI=0.02
# Construction-specific ticket diagnostics cover every adaptive shape from 2 through 7 legs.
# A shape still needs its own settled evidence when the Results-first lane is promoted.
RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS=(2,3,4,5,6,7)
RESULTS_FIRST_CONSTRUCTION_LEG_COUNT=2
RESULTS_FIRST_MIN_CONSTRUCTION_TICKETS=10
RESULTS_FIRST_MAX_CONSTRUCTION_LOSS_RATE=0.50
MIN_COMBINED_ODDS=4.0
VIRTUAL_MIN_PROB=0.65
TICKET_SPOILER_MIN_SAMPLE=50
TICKET_SPOILER_MIN_ACCURACY=0.90
PARTICIPANT_HISTORY_MIN_N=3
PARTICIPANT_HISTORY_MAX_BONUS=0.035
MAX_BATCHES=6
# Keep Builder candidates close to kickoff so participant evidence and market prices can be refreshed.
MAX_BUILDER_HORIZON_MINUTES=720
MAX_BATCH_KICKOFF_SPAN_MINUTES=60
MODEL_FIRST_MAX_KICKOFF_SPAN_MINUTES=270