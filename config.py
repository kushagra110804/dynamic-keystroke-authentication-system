"""
config.py

Every adjustable number in the project lives here, so that every decision
the system makes can be traced back to a visible, explainable setting.
Nothing in this file is "learned"; all values are chosen by the designer.
"""

# ---------------------------------------------------------------
# General
# ---------------------------------------------------------------
# Sentence used in the 2016 paper (Fig 5 / Fig 6). Letters and spaces only.
TARGET_TEXT = "the quick brown fox jumps over lazy dog"
DB_FILE = "keystroke.db"
REGISTRATION_SAMPLES = 10      # the paper also uses 10 samples

# ---------------------------------------------------------------
# Feature extraction (Phases 2 and 3)
# ---------------------------------------------------------------
# Pause = a gap between two consecutive keystrokes longer than this.
PAUSE_THRESHOLD_MS = 400.0

# ---------------------------------------------------------------
# Baseline method (inspired by the 2016 paper)
# ---------------------------------------------------------------
# The paper compares timing values against an "assumed threshold" and never
# states the number, so these are OUR concrete choices.
BASELINE_FEATURES = ["mean_dwell_ms", "mean_digraph_ms", "total_time_ms"]
BASELINE_TOLERANCE = 0.30      # a feature is "normal" if within +/-30% of stored mean
BASELINE_THRESHOLD = 70.0      # accept if score >= 70  (score = 100 - average % difference)

# ---------------------------------------------------------------
# Proposed method (timing + pause + correction + speed)
# ---------------------------------------------------------------
# Weights must add up to 1.0. They are a design choice, NOT tuned on test data.
FEATURE_WEIGHTS = {
    "mean_dwell_ms":          0.15,   # key hold time
    "mean_flight_nopause_ms": 0.15,   # gap between keys (pauses excluded)
    "digraph_match_ratio":    0.20,   # share of key-pair timings in normal range
    "typing_speed_cps":       0.10,   # characters per second
    "pause_count":            0.10,   # how many hesitations
    "mean_pause_ms":          0.10,   # how long the hesitations last
    "backspace_count":        0.10,   # how many corrections
    "mean_word_gap_ms":       0.10,   # time between words
}

FEATURE_LABELS = {
    "mean_dwell_ms":          "Mean dwell time (ms)",
    "mean_flight_ms":         "Mean flight time, all gaps (ms)",
    "mean_flight_nopause_ms": "Mean flight time, no pauses (ms)",
    "mean_digraph_ms":        "Mean digraph (press-to-press) (ms)",
    "total_time_ms":          "Total typing time (ms)",
    "typing_speed_cps":       "Typing speed (chars/sec)",
    "pause_count":            "Number of pauses",
    "mean_pause_ms":          "Mean pause duration (ms)",
    "longest_pause_ms":       "Longest pause (ms)",
    "backspace_count":        "Number of backspaces",
    "mean_word_gap_ms":       "Mean time between words (ms)",
    "digraph_match_ratio":    "Digraphs within normal range",
}

# A profile SD can be 0 or tiny (e.g. the user never paused in 10 samples).
# To avoid dividing by ~0 we use an "effective SD" = the largest of:
#   the real SD, 10% of the mean, and the absolute floor below.
RELATIVE_SD_FLOOR = 0.10
FEATURE_MIN_SD = {
    "mean_dwell_ms":          10.0,
    "mean_flight_nopause_ms": 15.0,
    "typing_speed_cps":        0.3,
    "pause_count":             0.7,
    "mean_pause_ms":         100.0,
    "backspace_count":         0.7,
    "mean_word_gap_ms":       25.0,
}

Z_LIMIT = 3.0       # z >= 3 standard deviations away  -> similarity 0
Z_FLAG = 2.0        # z > 2 -> feature is reported as "unusual"

# Digraph (key-pair) comparison
DIGRAPH_Z_LIMIT = 2.0        # a digraph is "in range" if within 2 effective SDs
DIGRAPH_MIN_SD = 15.0        # ms
DIGRAPH_MIN_SAMPLES = 3      # need at least 3 profile samples of a digraph
DIGRAPH_RATIO_FLAG = 0.60    # below 60% in-range -> reported as "unusual"

PROPOSED_THRESHOLD = 60.0    # accept if score >= 60 (out of 100)

# ---------------------------------------------------------------
# Experiment categories (Phase 7)
# ---------------------------------------------------------------
CATEGORIES = {
    "genuine_normal":     "Genuine user - normal typing",
    "genuine_variation":  "Genuine user - faster / slower typing",
    "impostor_natural":   "Impostor - own natural typing",
    "impostor_imitation": "Impostor - imitating genuine rhythm",
}
GENUINE_CATEGORIES = ["genuine_normal", "genuine_variation"]
IMPOSTOR_CATEGORIES = ["impostor_natural", "impostor_imitation"]

MIN_ATTEMPTS_FOR_EER = 10    # per class; below this EER is flagged as unreliable
