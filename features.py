"""
features.py   (Phase 2: timing features, Phase 3: pause/correction features)

Turns the raw press/release events from capture.py into numbers.

DEFINITIONS (all times in milliseconds)
  Dwell time   = key release time  - key press time        (how long a key is held)
  Flight time  = next key press    - previous key release  (gap between two keys;
                                                            negative = keys overlapped)
  Digraph time = next key press    - previous key press    (press-to-press of two
                                                            consecutive keys)
  Pause        = a gap (flight) longer than PAUSE_THRESHOLD_MS
  Word gap     = first letter of next word pressed - last letter of previous word released
  Typing speed = surviving characters / total time in seconds
  Backspaces   = number of times BackSpace was pressed

HOW CORRECTIONS ARE HANDLED
  We replay the keystrokes like a text box would: a normal key pushes a
  character, BackSpace removes the last one. The characters that "survive"
  form the final text. Timing features (dwell, flight, digraph, word gap) use
  only surviving characters. A digraph is measured only if the two surviving
  characters were typed one right after the other (nothing erased between them).
"""

import math

from config import PAUSE_THRESHOLD_MS

# Names of all single-number features stored for each sample.
SCALAR_FEATURE_NAMES = [
    "mean_dwell_ms",
    "mean_flight_ms",
    "mean_flight_nopause_ms",
    "mean_digraph_ms",
    "total_time_ms",
    "typing_speed_cps",
    "pause_count",
    "mean_pause_ms",
    "longest_pause_ms",
    "backspace_count",
    "mean_word_gap_ms",
]


# ---------------------------------------------------------------
# Small maths helpers (written out so every step is visible)
# ---------------------------------------------------------------
def average(values):
    """Mean of a list. Returns 0.0 for an empty list."""
    if len(values) == 0:
        return 0.0
    total = 0.0
    for value in values:
        total += value
    return total / len(values)


def standard_deviation(values):
    """Sample standard deviation (divides by n-1). 0.0 if fewer than 2 values."""
    count = len(values)
    if count < 2:
        return 0.0
    mean_value = average(values)
    sum_of_squares = 0.0
    for value in values:
        difference = value - mean_value
        sum_of_squares += difference * difference
    return math.sqrt(sum_of_squares / (count - 1))


# ---------------------------------------------------------------
# Step 1: pair presses with releases
# ---------------------------------------------------------------
def is_printable(key):
    """Letters, digits and space. (Keysym of a normal key is 1 character.)"""
    return len(key) == 1 or key == "space"


def is_backspace(key):
    return key == "BackSpace"


def build_keystrokes(events):
    """
    Combine each press with its release (matched by keycode).
    Returns keystrokes in the order they were pressed.
    A key that was never released is dropped.
    """
    waiting_for_release = {}
    keystrokes = []
    for event in events:
        if event["event"] == "press":
            keystroke = {
                "key": event["key"],
                "keycode": event["keycode"],
                "press_ms": event["time_ms"],
                "release_ms": None,
            }
            waiting_for_release[event["keycode"]] = keystroke
            keystrokes.append(keystroke)
        else:
            keystroke = waiting_for_release.pop(event["keycode"], None)
            if keystroke is not None:
                keystroke["release_ms"] = event["time_ms"]

    complete = []
    for keystroke in keystrokes:
        if keystroke["release_ms"] is not None:
            complete.append(keystroke)
    return complete


def find_surviving_keystrokes(actions):
    """
    Replay typing: normal key = add a character, BackSpace = remove the last one.
    Returns a list of (keystroke, index_in_actions) for characters that remain.
    The index lets us check whether two survivors were typed back-to-back.
    """
    survivors = []
    for index in range(len(actions)):
        keystroke = actions[index]
        if is_backspace(keystroke["key"]):
            if len(survivors) > 0:
                survivors.pop()
        else:
            survivors.append((keystroke, index))
    return survivors


# ---------------------------------------------------------------
# Step 2: compute all features of ONE typing sample
# ---------------------------------------------------------------
def extract_features(events):
    """
    Input : raw events list from KeystrokeRecorder
    Output: {"values": {feature_name: number}, "digraphs": {"pos:a>b": ms}}
    Raises ValueError if the sample is too short to analyse.
    """
    keystrokes = build_keystrokes(events)

    # Keep only typing keys and BackSpace (ignore Shift, Ctrl, etc.)
    actions = []
    for keystroke in keystrokes:
        if is_printable(keystroke["key"]) or is_backspace(keystroke["key"]):
            actions.append(keystroke)

    survivors = find_surviving_keystrokes(actions)
    if len(survivors) < 2:
        raise ValueError("Sample too short: need at least 2 characters.")

    # ---- Dwell time (Phase 2) ----
    dwell_times = []
    for keystroke, index in survivors:
        dwell = keystroke["release_ms"] - keystroke["press_ms"]
        dwell_times.append(dwell)

    # ---- Flight time and digraph time (Phase 2) ----
    all_flights = []
    flights_without_pauses = []
    digraph_times = []
    digraph_by_name = {}
    for position in range(len(survivors) - 1):
        first_key, first_index = survivors[position]
        second_key, second_index = survivors[position + 1]

        typed_back_to_back = (second_index == first_index + 1)
        if not typed_back_to_back:
            continue  # something was erased between them; skip this pair

        flight = second_key["press_ms"] - first_key["release_ms"]
        digraph = second_key["press_ms"] - first_key["press_ms"]

        all_flights.append(flight)
        if flight <= PAUSE_THRESHOLD_MS:
            flights_without_pauses.append(flight)
        digraph_times.append(digraph)

        name = "%d:%s>%s" % (position, first_key["key"], second_key["key"])
        digraph_by_name[name] = digraph

    # ---- Total time and typing speed (Phase 2) ----
    first_press = actions[0]["press_ms"]
    last_release = actions[0]["release_ms"]
    for keystroke in actions:
        if keystroke["release_ms"] > last_release:
            last_release = keystroke["release_ms"]
    total_time_ms = last_release - first_press
    if total_time_ms <= 0:
        raise ValueError("Sample has no duration.")
    typing_speed_cps = len(survivors) / (total_time_ms / 1000.0)

    # ---- Pauses (Phase 3): gap between consecutive actions > threshold ----
    pause_durations = []
    for i in range(len(actions) - 1):
        gap = actions[i + 1]["press_ms"] - actions[i]["release_ms"]
        if gap > PAUSE_THRESHOLD_MS:
            pause_durations.append(gap)

    longest_pause = 0.0
    for duration in pause_durations:
        if duration > longest_pause:
            longest_pause = duration

    # ---- Corrections (Phase 3) ----
    backspace_count = 0
    for keystroke in actions:
        if is_backspace(keystroke["key"]):
            backspace_count += 1

    # ---- Time between words (Phase 3) ----
    word_gaps = []
    for j in range(1, len(survivors) - 1):
        current_key = survivors[j][0]
        if current_key["key"] == "space":
            letter_before = survivors[j - 1][0]
            letter_after = survivors[j + 1][0]
            if letter_before["key"] != "space" and letter_after["key"] != "space":
                gap = letter_after["press_ms"] - letter_before["release_ms"]
                word_gaps.append(gap)

    values = {
        "mean_dwell_ms": average(dwell_times),
        "mean_flight_ms": average(all_flights),
        "mean_flight_nopause_ms": average(flights_without_pauses),
        "mean_digraph_ms": average(digraph_times),
        "total_time_ms": total_time_ms,
        "typing_speed_cps": typing_speed_cps,
        "pause_count": float(len(pause_durations)),
        "mean_pause_ms": average(pause_durations),
        "longest_pause_ms": longest_pause,
        "backspace_count": float(backspace_count),
        "mean_word_gap_ms": average(word_gaps),
    }
    return {"values": values, "digraphs": digraph_by_name}


# ---------------------------------------------------------------
# Step 3: build the user's profile from the registration samples
# ---------------------------------------------------------------
def build_profile(feature_list):
    """
    For each feature: mean, standard deviation, min and max over the samples.
    For each digraph: mean, standard deviation and how many samples had it.
    """
    value_stats = {}
    for name in SCALAR_FEATURE_NAMES:
        numbers = []
        for features in feature_list:
            numbers.append(features["values"][name])
        value_stats[name] = {
            "mean": average(numbers),
            "sd": standard_deviation(numbers),
            "min": min(numbers),
            "max": max(numbers),
        }

    digraph_lists = {}
    for features in feature_list:
        for name, time_ms in features["digraphs"].items():
            if name not in digraph_lists:
                digraph_lists[name] = []
            digraph_lists[name].append(time_ms)

    digraph_stats = {}
    for name, numbers in digraph_lists.items():
        digraph_stats[name] = {
            "mean": average(numbers),
            "sd": standard_deviation(numbers),
            "count": len(numbers),
        }

    return {
        "num_samples": len(feature_list),
        "values": value_stats,
        "digraphs": digraph_stats,
    }
