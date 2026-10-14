"""
auth.py   (Phase 5: baseline method, Phase 6: proposed method)

Both methods return a result dictionary with the same shape:

    {
      "method":   "baseline" or "proposed",
      "accepted": True / False,
      "score":    0..100 (higher = more like the genuine user),
      "threshold": score needed to be accepted,
      "rows":     one row per feature: what was compared and how many points it gave,
      "reasons":  plain-English reasons (filled only when rejected),
      "unusual":  features that were far from the user's normal (always filled)
    }

No machine learning: only means, standard deviations, z-scores and a weighted sum.
"""

import config


# ===============================================================
# BASELINE  (Phase 5)  - simple fixed-threshold timing method
# ===============================================================
# Idea (from the 2016 paper): store the user's average timings, then compare
# the login attempt with them using a fixed threshold.
#
# For each of 3 timing features:
#     relative difference = |attempt - stored mean| / stored mean
#     similarity          = 1 - relative difference     (not below 0)
#     points              = (100 / 3) * similarity
# Score = sum of points.  Example: all three features 10% off -> score 90.
# Accept if score >= BASELINE_THRESHOLD (70, i.e. about 30% average difference).
def authenticate_baseline(features, profile, text_matches=True, threshold=None):
    if threshold is None:
        threshold = config.BASELINE_THRESHOLD

    feature_count = len(config.BASELINE_FEATURES)
    weight = 1.0 / feature_count
    rows = []
    unusual = []
    score = 0.0

    for name in config.BASELINE_FEATURES:
        attempt_value = features["values"][name]
        stored_mean = profile["values"][name]["mean"]

        if stored_mean > 0:
            relative_difference = abs(attempt_value - stored_mean) / stored_mean
        else:
            relative_difference = 1.0

        similarity = 1.0 - relative_difference
        if similarity < 0.0:
            similarity = 0.0
        points = weight * similarity * 100.0
        score += points

        detail = "yours %.1f | stored mean %.1f | difference %.1f%%" % (
            attempt_value, stored_mean, relative_difference * 100.0)
        rows.append({
            "name": name,
            "label": config.FEATURE_LABELS[name],
            "detail": detail,
            "similarity": similarity,
            "weight": weight,
            "points": points,
            "max_points": weight * 100.0,
        })
        if relative_difference > config.BASELINE_TOLERANCE:
            unusual.append("%s is %.0f%% away from your stored mean (allowed: %.0f%%)" % (
                config.FEATURE_LABELS[name], relative_difference * 100.0,
                config.BASELINE_TOLERANCE * 100.0))

    accepted = text_matches and score >= threshold
    reasons = []
    if not accepted:
        if not text_matches:
            reasons.append("The typed text does not match the required sentence.")
        else:
            reasons.append("Score %.1f is below the threshold %.1f." % (score, threshold))
            reasons.extend(unusual)

    return {"method": "baseline", "accepted": accepted, "score": score,
            "threshold": threshold, "rows": rows, "reasons": reasons, "unusual": unusual}


# ===============================================================
# PROPOSED  (Phase 6) - timing + pause + correction + speed
# ===============================================================
def effective_sd(feature_name, mean, sd):
    """
    The SD we actually divide by. A profile SD can be 0 (e.g. the user never
    paused), which would make any deviation look infinite. So we use the largest of:
        the real SD,  10% of the mean,  an absolute minimum for that feature.
    """
    relative_floor = config.RELATIVE_SD_FLOOR * abs(mean)
    absolute_floor = config.FEATURE_MIN_SD[feature_name]
    result = sd
    if relative_floor > result:
        result = relative_floor
    if absolute_floor > result:
        result = absolute_floor
    return result


def compare_digraphs(attempt_digraphs, profile_digraphs):
    """
    For every key pair in the attempt that the profile knows well (>= 3 samples),
    check whether its press-to-press time is within DIGRAPH_Z_LIMIT effective SDs
    of the profile mean. Returns (ratio_in_range, how_many_compared, how_many_matched).
    """
    compared = 0
    matched = 0
    for name, time_ms in attempt_digraphs.items():
        stats = profile_digraphs.get(name)
        if stats is None or stats["count"] < config.DIGRAPH_MIN_SAMPLES:
            continue
        sd = stats["sd"]
        if config.RELATIVE_SD_FLOOR * stats["mean"] > sd:
            sd = config.RELATIVE_SD_FLOOR * stats["mean"]
        if config.DIGRAPH_MIN_SD > sd:
            sd = config.DIGRAPH_MIN_SD
        z_score = abs(time_ms - stats["mean"]) / sd
        compared += 1
        if z_score <= config.DIGRAPH_Z_LIMIT:
            matched += 1
    if compared == 0:
        return 0.0, 0, 0
    return matched / float(compared), compared, matched


# For each feature:
#     z          = |attempt - profile mean| / effective SD      ("how many SDs away")
#     similarity = 1 - z / 3  (never below 0; z=0 -> 1.0, z>=3 -> 0.0)
#     points     = weight * similarity * 100
# Digraph feature: similarity = share of key-pair timings inside the normal range.
# Score = sum of points (0..100). Accept if text matches AND score >= threshold.
def authenticate_proposed(features, profile, text_matches=True, threshold=None):
    if threshold is None:
        threshold = config.PROPOSED_THRESHOLD

    rows = []
    unusual = []
    score = 0.0

    for name, weight in config.FEATURE_WEIGHTS.items():
        z_score = None
        flagged = False

        if name == "digraph_match_ratio":
            ratio, compared, matched = compare_digraphs(features["digraphs"], profile["digraphs"])
            similarity = ratio
            detail = "%d of %d key-pair timings in normal range" % (matched, compared)
            flagged = similarity < config.DIGRAPH_RATIO_FLAG
        else:
            attempt_value = features["values"][name]
            stats = profile["values"][name]
            sd = effective_sd(name, stats["mean"], stats["sd"])
            z_score = abs(attempt_value - stats["mean"]) / sd
            similarity = 1.0 - z_score / config.Z_LIMIT
            if similarity < 0.0:
                similarity = 0.0
            detail = "yours %.1f | normal %.1f (+/- %.1f) | z = %.2f" % (
                attempt_value, stats["mean"], sd, z_score)
            flagged = z_score > config.Z_FLAG

        points = weight * similarity * 100.0
        score += points
        row = {
            "name": name,
            "label": config.FEATURE_LABELS[name],
            "detail": detail,
            "similarity": similarity,
            "weight": weight,
            "points": points,
            "max_points": weight * 100.0,
            "lost_points": weight * 100.0 - points,
            "z": z_score,
            "flagged": flagged,
        }
        rows.append(row)

    # Unusual features, biggest loss of points first
    flagged_rows = []
    for row in rows:
        if row["flagged"]:
            flagged_rows.append(row)
    flagged_rows.sort(key=lambda r: r["lost_points"], reverse=True)
    for row in flagged_rows:
        unusual.append("%s: %s (lost %.1f of %.1f points)" % (
            row["label"], row["detail"], row["lost_points"], row["max_points"]))

    accepted = text_matches and score >= threshold
    reasons = []
    if not accepted:
        if not text_matches:
            reasons.append("The typed text does not match the required sentence.")
        else:
            reasons.append("Overall score %.1f is below the threshold %.1f." % (score, threshold))
            if len(unusual) > 0:
                reasons.extend(unusual)
            else:
                reasons.append("No single feature was far off; many small differences added up.")

    return {"method": "proposed", "accepted": accepted, "score": score,
            "threshold": threshold, "rows": rows, "reasons": reasons, "unusual": unusual}


METHODS = {
    "baseline": authenticate_baseline,
    "proposed": authenticate_proposed,
}
