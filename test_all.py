"""
test_all.py   (Phase 9)

Checks that the code is correct. Run:  python test_all.py

IMPORTANT: the typing data below is SYNTHETIC (made by a random generator).
It exists only to prove the code runs and the maths is right.
It is NOT experimental data and must never appear in your results.
Tests use a temporary database, never your real keystroke.db.
"""

import os
import random
import tempfile

import auth
import config
import database
import evaluation
import features
from capture import KeystrokeRecorder


def check(condition, message):
    if not condition:
        raise AssertionError("FAILED: " + message)
    print("  PASS:", message)


def close(a, b, tolerance=0.001):
    return abs(a - b) < tolerance


# ---------------------------------------------------------------
# Helper: build raw events from a simple list of (key, keycode, press, release)
# ---------------------------------------------------------------
def events_from_keystrokes(keystroke_list):
    events = []
    for key, keycode, press_ms, release_ms in keystroke_list:
        events.append({"event": "press", "key": key, "keycode": keycode, "time_ms": press_ms})
        events.append({"event": "release", "key": key, "keycode": keycode, "time_ms": release_ms})
    events.sort(key=lambda e: e["time_ms"])
    return events


# ---------------------------------------------------------------
# Test 1: hand-calculated features
# ---------------------------------------------------------------
def test_feature_maths():
    print("Test 1: feature maths (checked by hand)")
    # a: 0-100, b: 150-250, c: 900-1000
    events = events_from_keystrokes([("a", 65, 0, 100), ("b", 66, 150, 250), ("c", 67, 900, 1000)])
    result = features.extract_features(events)["values"]
    check(close(result["mean_dwell_ms"], 100.0), "dwell = 100 for every key")
    # flights: b-a = 150-100 = 50 ; c-b = 900-250 = 650 -> mean 350
    check(close(result["mean_flight_ms"], 350.0), "mean flight of 50 and 650 = 350")
    check(close(result["mean_flight_nopause_ms"], 50.0), "flight without the pause = 50")
    # digraphs (press-to-press): 150 and 750 -> mean 450
    check(close(result["mean_digraph_ms"], 450.0), "mean digraph of 150 and 750 = 450")
    check(close(result["total_time_ms"], 1000.0), "total time = 1000")
    check(close(result["typing_speed_cps"], 3.0), "3 chars in 1 s = 3 chars/sec")
    check(close(result["pause_count"], 1.0), "one gap (650) above the 400 ms threshold")
    check(close(result["mean_pause_ms"], 650.0), "pause duration = 650")
    check(close(result["backspace_count"], 0.0), "no backspaces")


def test_backspace_handling():
    print("Test 2: corrections / backspace")
    # type a, x (wrong), BackSpace, b  -> final text "ab"
    events = events_from_keystrokes([
        ("a", 65, 0, 80), ("x", 88, 120, 200), ("BackSpace", 8, 240, 300), ("b", 66, 340, 420)])
    extracted = features.extract_features(events)
    check(close(extracted["values"]["backspace_count"], 1.0), "one backspace counted")
    check(len(extracted["digraphs"]) == 0, "a and b were not typed back-to-back, so no digraph")
    check(close(extracted["values"]["mean_dwell_ms"], 80.0), "dwell uses surviving keys only (a=80, b=80)")


def test_word_gap_and_shift():
    print("Test 3: word gap, Shift ignored")
    events = events_from_keystrokes([
        ("Shift_L", 50, 0, 400),
        ("h", 72, 10, 90), ("i", 73, 130, 200), ("space", 32, 250, 320), ("y", 89, 400, 470), ("o", 79, 510, 580)])
    extracted = features.extract_features(events)
    # word gap = press of 'y' (400) - release of 'i' (200) = 200
    check(close(extracted["values"]["mean_word_gap_ms"], 200.0), "word gap = 200")
    check(extracted["values"]["backspace_count"] == 0, "Shift did not count as a typing key")


def test_recorder():
    print("Test 4: recorder auto-repeat and orphan release")
    recorder = KeystrokeRecorder()
    check(recorder.record_release(1, timestamp_s=1.0) is None, "orphan release ignored")
    recorder.record_press(1, "a", timestamp_s=2.0)
    check(recorder.record_press(1, "a", timestamp_s=2.1) is None, "auto-repeat press ignored")
    recorder.record_release(1, timestamp_s=2.2)
    check(len(recorder.events) == 2, "exactly one press and one release stored")


# ---------------------------------------------------------------
# Test 5: FAR / FRR / accuracy / EER on known numbers
# ---------------------------------------------------------------
def test_metrics():
    print("Test 5: FAR, FRR, accuracy, EER on known scores")
    genuine = [90, 80, 70, 60]
    impostor = [50, 40, 65, 30]
    check(close(evaluation.calculate_frr(genuine, 60), 0.0), "FRR at threshold 60 = 0/4")
    check(close(evaluation.calculate_far(impostor, 60), 0.25), "FAR at threshold 60 = 1/4 (65 accepted)")
    check(close(evaluation.calculate_accuracy(genuine, impostor, 60), 7.0 / 8.0), "accuracy = 7/8")
    check(close(evaluation.calculate_frr(genuine, 75), 0.5), "FRR at threshold 75 = 2/4")

    perfect = evaluation.calculate_eer([80, 90], [10, 20])
    check(close(perfect["eer"], 0.0), "perfectly separated scores give EER = 0")

    identical = evaluation.calculate_eer([50, 50], [50, 50])
    check(identical["eer"] is not None and identical["eer"] > 0.0, "identical scores give EER > 0")
    check(evaluation.calculate_eer([], [10]) is None, "EER is None when a class is empty")


# ---------------------------------------------------------------
# Synthetic typist generator (TEST ONLY)
# ---------------------------------------------------------------
def make_synthetic_sample(rng, dwell, flight, jitter, pause_chance=0.0, typo_chance=0.0):
    events = []
    clock = 0.0
    for character in config.TARGET_TEXT:
        if character == " ":
            key, keycode = "space", 32
        else:
            key, keycode = character, ord(character)

        if rng.random() < typo_chance:  # type a wrong key, then correct it
            events.append({"event": "press", "key": "x", "keycode": 120, "time_ms": clock})
            events.append({"event": "release", "key": "x", "keycode": 120, "time_ms": clock + dwell})
            clock += dwell + 60
            events.append({"event": "press", "key": "BackSpace", "keycode": 8, "time_ms": clock})
            events.append({"event": "release", "key": "BackSpace", "keycode": 8, "time_ms": clock + dwell})
            clock += dwell + 80

        this_dwell = max(20.0, rng.gauss(dwell, jitter * 0.4))
        events.append({"event": "press", "key": key, "keycode": keycode, "time_ms": clock})
        events.append({"event": "release", "key": key, "keycode": keycode, "time_ms": clock + this_dwell})

        this_flight = max(5.0, rng.gauss(flight, jitter))
        if rng.random() < pause_chance:
            this_flight += 600.0
        clock += this_dwell + this_flight
    return events


def test_database_and_pipeline():
    print("Test 6: database + registration + authentication + evaluation (synthetic data)")
    rng = random.Random(12345)
    temp_folder = tempfile.mkdtemp()
    conn = database.connect(os.path.join(temp_folder, "test.db"))
    database.create_tables(conn)

    registration = []
    for i in range(config.REGISTRATION_SAMPLES):
        registration.append(make_synthetic_sample(rng, 95, 110, 15))
    user_id, profile = database.register_user(conn, "alice", config.TARGET_TEXT, registration)
    check(profile["num_samples"] == 10, "profile built from 10 samples")
    check(database.get_user(conn, "alice") is not None, "user stored in SQLite")
    check(database.get_profile(conn, user_id)["num_samples"] == 10, "profile can be read back")

    # Synthetic experiment samples
    for i in range(20):
        database.add_experiment_sample(conn, user_id, "genuine_normal", "alice", make_synthetic_sample(rng, 95, 110, 15))
    for i in range(10):
        database.add_experiment_sample(conn, user_id, "genuine_variation", "alice", make_synthetic_sample(rng, 80, 90, 15))
    for i in range(20):
        database.add_experiment_sample(conn, user_id, "impostor_natural", "bob",
                                       make_synthetic_sample(rng, 125, 170, 30, pause_chance=0.08, typo_chance=0.05))
    for i in range(20):
        database.add_experiment_sample(conn, user_id, "impostor_imitation", "bob",
                                       make_synthetic_sample(rng, 100, 115, 25, pause_chance=0.05, typo_chance=0.04))

    results = evaluation.run_evaluation(conn, user_id)
    check(len(results["records"]) == 70, "all 70 experiment samples were scored")
    check(results["skipped"] == 0, "no samples skipped")
    check(results["baseline"]["mean_decision_ms"] > 0, "decision time measured (baseline)")
    check(results["proposed"]["mean_decision_ms"] > 0, "decision time measured (proposed)")

    # Weights must sum to 1
    check(close(sum(config.FEATURE_WEIGHTS.values()), 1.0), "proposed weights add up to 1.0")

    # Result structure and explainability
    sample_features = features.extract_features(registration[0])
    outcome = auth.authenticate_proposed(sample_features, profile, True)
    points_total = 0.0
    for row in outcome["rows"]:
        points_total += row["points"]
    check(close(points_total, outcome["score"]), "score equals the sum of per-feature points")
    wrong_text = auth.authenticate_proposed(sample_features, profile, False)
    check(not wrong_text["accepted"] and len(wrong_text["reasons"]) > 0, "wrong text is rejected with a reason")

    print()
    print("  >>> SYNTHETIC DATA - code check only, NOT research results <<<")
    for metric, base_value, prop_value in evaluation.build_comparison_rows(results):
        print("  %-62s %-16s %-16s" % (metric, base_value, prop_value))

    csv_summary = os.path.join(temp_folder, "s.csv")
    csv_samples = os.path.join(temp_folder, "p.csv")
    evaluation.export_csv(results, csv_summary, csv_samples)
    check(os.path.getsize(csv_summary) > 0 and os.path.getsize(csv_samples) > 0, "CSV export works")

    database.delete_user(conn, "alice")
    check(len(database.get_experiment_samples(conn)) == 0, "deleting a user deletes their samples")
    conn.close()


if __name__ == "__main__":
    test_feature_maths()
    test_backspace_handling()
    test_word_gap_and_shift()
    test_recorder()
    test_metrics()
    test_database_and_pipeline()
    print("\nALL TESTS PASSED")
