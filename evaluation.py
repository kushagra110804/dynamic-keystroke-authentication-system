"""
evaluation.py   (Phase 7)

Compares the baseline and proposed methods on the experiment samples stored
in the database. Nothing here invents data: every number comes from samples
that were actually typed and saved.

DEFINITIONS
  FAR (False Acceptance Rate) = impostor attempts accepted / all impostor attempts
  FRR (False Rejection Rate)  = genuine attempts rejected  / all genuine attempts
  Accuracy          = correct decisions / all attempts   (depends on the genuine:impostor mix)
  Balanced accuracy = (1 - FAR + 1 - FRR) / 2            (not affected by the mix)
  EER (Equal Error Rate) = the error rate at the threshold where FAR = FRR.
        Found by trying thresholds 0, 0.5, ..., 100 and taking the one where
        |FAR - FRR| is smallest; EER = (FAR + FRR) / 2 there.
        NOTE: the 2016 paper defines EER as FAR/FRR, which is incorrect.
  Decision time = time to extract features and compute the decision (ms).
        Typing time is NOT included.
"""

import csv
import time

import auth
import config
import database
import features

METHOD_NAMES = ["baseline", "proposed"]


# ---------------------------------------------------------------
# Basic rate calculations
# ---------------------------------------------------------------
def calculate_far(impostor_scores, threshold):
    """Fraction of impostor attempts with score >= threshold. None if no attempts."""
    if len(impostor_scores) == 0:
        return None
    false_accepts = 0
    for score in impostor_scores:
        if score >= threshold:
            false_accepts += 1
    return false_accepts / float(len(impostor_scores))


def calculate_frr(genuine_scores, threshold):
    """Fraction of genuine attempts with score < threshold. None if no attempts."""
    if len(genuine_scores) == 0:
        return None
    false_rejects = 0
    for score in genuine_scores:
        if score < threshold:
            false_rejects += 1
    return false_rejects / float(len(genuine_scores))


def calculate_accuracy(genuine_scores, impostor_scores, threshold):
    """Correct decisions / all decisions. None if there are no attempts."""
    total = len(genuine_scores) + len(impostor_scores)
    if total == 0:
        return None
    correct = 0
    for score in genuine_scores:
        if score >= threshold:
            correct += 1
    for score in impostor_scores:
        if score < threshold:
            correct += 1
    return correct / float(total)


def calculate_eer(genuine_scores, impostor_scores):
    """
    Sweep thresholds 0..100 in steps of 0.5 and find where FAR and FRR are closest.
    Returns a dictionary, or None if either class has no attempts.
    """
    if len(genuine_scores) == 0 or len(impostor_scores) == 0:
        return None

    curve = []
    best = None
    for step in range(0, 202):
        threshold = step * 0.5
        far = calculate_far(impostor_scores, threshold)
        frr = calculate_frr(genuine_scores, threshold)
        curve.append((threshold, far, frr))
        gap = abs(far - frr)
        if best is None or gap < best["gap"]:
            best = {"gap": gap, "threshold": threshold, "far": far, "frr": frr}

    reliable = (len(genuine_scores) >= config.MIN_ATTEMPTS_FOR_EER and
                len(impostor_scores) >= config.MIN_ATTEMPTS_FOR_EER)
    return {
        "eer": (best["far"] + best["frr"]) / 2.0,
        "threshold": best["threshold"],
        "far": best["far"],
        "frr": best["frr"],
        "reliable": reliable,
        "curve": curve,
    }


# ---------------------------------------------------------------
# Scoring every experiment sample with both methods
# ---------------------------------------------------------------
def score_one_sample(sample, profile):
    """
    Runs both methods on one stored sample and times each decision.
    Returns None if the sample cannot be analysed.
    """
    record = {
        "sample_id": sample["id"],
        "user_id": sample["user_id"],
        "username": sample["username"],
        "category": sample["category"],
        "tester_name": sample["tester_name"],
        "is_genuine": sample["category"] in config.GENUINE_CATEGORIES,
    }
    for method_name in METHOD_NAMES:
        start = time.perf_counter()
        try:
            extracted = features.extract_features(sample["events"])
        except ValueError:
            return None
        result = auth.METHODS[method_name](extracted, profile, True)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        record[method_name + "_score"] = result["score"]
        record[method_name + "_accepted"] = result["accepted"]
        record[method_name + "_ms"] = elapsed_ms
    return record


def score_all_samples(samples, profiles):
    """profiles: {user_id: profile}. Returns (records, number_skipped)."""
    records = []
    skipped = 0
    for sample in samples:
        profile = profiles.get(sample["user_id"])
        if profile is None:
            skipped += 1
            continue
        record = score_one_sample(sample, profile)
        if record is None:
            skipped += 1
        else:
            records.append(record)
    return records, skipped


# ---------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------
def category_rate(records, category, method_name, is_genuine):
    """FRR for a genuine category, or FAR for an impostor category (at the default threshold)."""
    count = 0
    errors = 0
    for record in records:
        if record["category"] != category:
            continue
        count += 1
        accepted = record[method_name + "_accepted"]
        if is_genuine and not accepted:
            errors += 1
        if (not is_genuine) and accepted:
            errors += 1
    if count == 0:
        return None, 0
    return errors / float(count), count


def summarize_method(records, method_name):
    genuine_scores = []
    impostor_scores = []
    decision_times = []
    false_rejects = 0
    false_accepts = 0
    for record in records:
        score = record[method_name + "_score"]
        decision_times.append(record[method_name + "_ms"])
        if record["is_genuine"]:
            genuine_scores.append(score)
            if not record[method_name + "_accepted"]:
                false_rejects += 1
        else:
            impostor_scores.append(score)
            if record[method_name + "_accepted"]:
                false_accepts += 1

    if method_name == "baseline":
        default_threshold = config.BASELINE_THRESHOLD
    else:
        default_threshold = config.PROPOSED_THRESHOLD

    frr = None
    if len(genuine_scores) > 0:
        frr = false_rejects / float(len(genuine_scores))
    far = None
    if len(impostor_scores) > 0:
        far = false_accepts / float(len(impostor_scores))

    balanced_accuracy = None
    if frr is not None and far is not None:
        balanced_accuracy = ((1.0 - far) + (1.0 - frr)) / 2.0

    summary = {
        "method": method_name,
        "threshold": default_threshold,
        "genuine_count": len(genuine_scores),
        "impostor_count": len(impostor_scores),
        "frr": frr,
        "far": far,
        "accuracy": calculate_accuracy(genuine_scores, impostor_scores, default_threshold),
        "balanced_accuracy": balanced_accuracy,
        "eer_info": calculate_eer(genuine_scores, impostor_scores),
        "mean_decision_ms": features.average(decision_times),
        "by_category": {},
    }
    for category in config.GENUINE_CATEGORIES:
        summary["by_category"][category] = category_rate(records, category, method_name, True)
    for category in config.IMPOSTOR_CATEGORIES:
        summary["by_category"][category] = category_rate(records, category, method_name, False)
    return summary


def run_evaluation(conn, user_id=None):
    """
    Evaluate every stored experiment sample (or only those for one profile owner).
    Returns {"records", "skipped", "baseline", "proposed"}.
    """
    samples = database.get_experiment_samples(conn, user_id)
    profiles = {}
    for sample in samples:
        if sample["user_id"] not in profiles:
            profiles[sample["user_id"]] = database.get_profile(conn, sample["user_id"])

    records, skipped = score_all_samples(samples, profiles)
    results = {"records": records, "skipped": skipped}
    for method_name in METHOD_NAMES:
        results[method_name] = summarize_method(records, method_name)
    return results


# ---------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------
def percent_text(value):
    if value is None:
        return "n/a"
    return "%.1f%%" % (value * 100.0)


def build_comparison_rows(results):
    """List of (metric name, baseline text, proposed text) for tables."""
    base = results["baseline"]
    prop = results["proposed"]
    rows = []

    rows.append(("Genuine attempts (n)", str(base["genuine_count"]), str(prop["genuine_count"])))
    rows.append(("Impostor attempts (n)", str(base["impostor_count"]), str(prop["impostor_count"])))
    rows.append(("Default accept threshold (score)", "%.1f" % base["threshold"], "%.1f" % prop["threshold"]))

    for category in config.GENUINE_CATEGORIES:
        label = "FRR - " + config.CATEGORIES[category]
        b_rate, b_count = base["by_category"][category]
        p_rate, p_count = prop["by_category"][category]
        rows.append((label + " (n=%d)" % b_count, percent_text(b_rate), percent_text(p_rate)))
    rows.append(("FRR - overall", percent_text(base["frr"]), percent_text(prop["frr"])))

    for category in config.IMPOSTOR_CATEGORIES:
        label = "FAR - " + config.CATEGORIES[category]
        b_rate, b_count = base["by_category"][category]
        p_rate, p_count = prop["by_category"][category]
        rows.append((label + " (n=%d)" % b_count, percent_text(b_rate), percent_text(p_rate)))
    rows.append(("FAR - overall", percent_text(base["far"]), percent_text(prop["far"])))

    rows.append(("Accuracy at default threshold", percent_text(base["accuracy"]), percent_text(prop["accuracy"])))
    rows.append(("Balanced accuracy", percent_text(base["balanced_accuracy"]), percent_text(prop["balanced_accuracy"])))

    base_eer = base["eer_info"]
    prop_eer = prop["eer_info"]
    if base_eer is None or prop_eer is None:
        rows.append(("EER", "n/a", "n/a"))
        rows.append(("Threshold at EER", "n/a", "n/a"))
    else:
        base_text = percent_text(base_eer["eer"])
        prop_text = percent_text(prop_eer["eer"])
        if not base_eer["reliable"]:
            base_text += " (few samples)"
        if not prop_eer["reliable"]:
            prop_text += " (few samples)"
        rows.append(("EER", base_text, prop_text))
        rows.append(("Threshold at EER", "%.1f" % base_eer["threshold"], "%.1f" % prop_eer["threshold"]))

    rows.append(("Mean decision time (ms)", "%.3f" % base["mean_decision_ms"], "%.3f" % prop["mean_decision_ms"]))
    return rows


def export_csv(results, summary_path="results_summary.csv", samples_path="results_samples.csv"):
    """Write the comparison table and the per-sample scores to CSV files."""
    with open(summary_path, "w", newline="") as summary_file:
        writer = csv.writer(summary_file)
        writer.writerow(["Metric", "Baseline", "Proposed"])
        for row in build_comparison_rows(results):
            writer.writerow(row)

    with open(samples_path, "w", newline="") as samples_file:
        writer = csv.writer(samples_file)
        writer.writerow(["sample_id", "profile_owner", "tester", "category", "is_genuine",
                         "baseline_score", "baseline_accepted", "baseline_ms",
                         "proposed_score", "proposed_accepted", "proposed_ms"])
        for r in results["records"]:
            writer.writerow([r["sample_id"], r["username"], r["tester_name"], r["category"],
                             r["is_genuine"],
                             "%.2f" % r["baseline_score"], r["baseline_accepted"], "%.4f" % r["baseline_ms"],
                             "%.2f" % r["proposed_score"], r["proposed_accepted"], "%.4f" % r["proposed_ms"]])


if __name__ == "__main__":
    connection = database.connect()
    database.create_tables(connection)
    evaluation_results = run_evaluation(connection)
    print("Samples evaluated: %d (skipped: %d)" % (
        len(evaluation_results["records"]), evaluation_results["skipped"]))
    for metric, base_value, prop_value in build_comparison_rows(evaluation_results):
        print("%-60s %-18s %-18s" % (metric, base_value, prop_value))
