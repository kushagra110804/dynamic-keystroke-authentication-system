"""
capture.py  (Phase 1)

Records raw key-press and key-release events with timestamps.
This file has NO GUI code, so it can be tested on its own.

Each recorded event is a dictionary:
    {
        "event":   "press" or "release",
        "key":     readable name of the key, e.g. "a", "space", "BackSpace",
        "keycode": hardware code of the key (used to pair press with release),
        "time_ms": milliseconds since the FIRST key press of this sample
    }
"""

import time


class KeystrokeRecorder:
    def __init__(self):
        self.reset()

    def reset(self):
        """Start a fresh, empty sample."""
        self.events = []        # list of event dictionaries, in time order
        self.keys_down = {}     # keycode -> label, for keys currently held down
        self.start_time_s = None  # clock value at the first key press

    def _to_relative_ms(self, timestamp_s):
        """Convert a clock reading (seconds) to ms since the first press."""
        if self.start_time_s is None:
            self.start_time_s = timestamp_s
        return (timestamp_s - self.start_time_s) * 1000.0

    def record_press(self, keycode, label, timestamp_s=None):
        """
        Record a key press. Returns the event dictionary,
        or None if it was ignored (key already held = auto-repeat).
        timestamp_s is only given in tests; normally the real clock is used.
        """
        if timestamp_s is None:
            timestamp_s = time.perf_counter()

        if keycode in self.keys_down:
            return None  # auto-repeat of a key that is still held down

        time_ms = self._to_relative_ms(timestamp_s)
        self.keys_down[keycode] = label
        event = {
            "event": "press",
            "key": label,
            "keycode": keycode,
            "time_ms": time_ms,
        }
        self.events.append(event)
        return event

    def record_release(self, keycode, timestamp_s=None):
        """
        Record a key release. Returns the event dictionary,
        or None if we never saw the matching press (orphan release).
        """
        if timestamp_s is None:
            timestamp_s = time.perf_counter()

        if keycode not in self.keys_down:
            return None  # released a key that was pressed before the sample began

        # Use the label saved at press time, so Shift+a always releases as "A"
        label = self.keys_down.pop(keycode)
        time_ms = self._to_relative_ms(timestamp_s)
        event = {
            "event": "release",
            "key": label,
            "keycode": keycode,
            "time_ms": time_ms,
        }
        self.events.append(event)
        return event

    # ---- small helper functions used by the GUI summary ----

    def count_presses(self):
        count = 0
        for event in self.events:
            if event["event"] == "press":
                count += 1
        return count

    def count_releases(self):
        count = 0
        for event in self.events:
            if event["event"] == "release":
                count += 1
        return count

    def total_duration_ms(self):
        """Time from the first event to the last event."""
        if len(self.events) == 0:
            return 0.0
        return self.events[-1]["time_ms"]

    def keys_still_down(self):
        """Number of keys pressed but never released."""
        return len(self.keys_down)


# ---------------------------------------------------------------
# Self-test: run  python capture.py  to check the recorder logic.
# We pass fake timestamps so the result is predictable.
# ---------------------------------------------------------------
if __name__ == "__main__":
    recorder = KeystrokeRecorder()

    # Orphan release (no matching press) must be ignored
    assert recorder.record_release(40, timestamp_s=5.000) is None

    recorder.record_press(43, "h", timestamp_s=10.000)      # press h at 0 ms
    recorder.record_press(43, "h", timestamp_s=10.030)      # auto-repeat: ignored
    recorder.record_release(43, timestamp_s=10.095)         # release h at 95 ms
    recorder.record_press(31, "i", timestamp_s=10.150)      # press i at 150 ms
    recorder.record_release(31, timestamp_s=10.240)         # release i at 240 ms

    for event in recorder.events:
        print(event)

    assert len(recorder.events) == 4
    assert abs(recorder.events[1]["time_ms"] - 95.0) < 0.001
    assert abs(recorder.total_duration_ms() - 240.0) < 0.001
    assert recorder.keys_still_down() == 0
    print("capture.py self-test PASSED")
