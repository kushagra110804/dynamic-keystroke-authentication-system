"""
app.py   (Phases 1, 4, 5, 6, 8)

Tkinter application with four tabs:
  1. Register      - collect 10 samples, build and store the user's profile
  2. Authenticate  - type the sentence, see baseline AND proposed decisions
  3. Experiment    - record labelled test samples (genuine / impostor ...)
  4. Results       - FAR, FRR, accuracy, EER, decision time + FAR/FRR curves

Run:  python app.py
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox

import auth
import config
import database
import evaluation
import features
import view_data
from capture import KeystrokeRecorder


# ===============================================================
# Reusable typing box (Phase 1 capture logic inside a widget)
# ===============================================================
class TypingBox(ttk.Frame):
    """
    Shows the target sentence and records key events while the user types.
    When the user presses Enter (and all keys are released) it calls
        on_sample_done(events, typed_text)
    and then clears itself, ready for the next sample.
    """

    def __init__(self, parent, on_sample_done):
        ttk.Frame.__init__(self, parent)
        self.on_sample_done = on_sample_done
        self.recorder = KeystrokeRecorder()
        self.finish_requested = False

        ttk.Label(self, text="Type this sentence exactly, then press Enter:").pack(anchor="w")
        ttk.Label(self, text=config.TARGET_TEXT, font=("Courier", 14, "bold")).pack(anchor="w", pady=(2, 6))

        self.entry = ttk.Entry(self, font=("Courier", 14), width=50)
        self.entry.pack(fill="x")
        self.entry.bind("<KeyPress>", self.on_key_press)
        self.entry.bind("<KeyRelease>", self.on_key_release)

        ttk.Button(self, text="Clear (restart this sample)", command=self.reset).pack(anchor="w", pady=4)

    def on_key_press(self, event):
        if event.keysym in ("Return", "KP_Enter"):
            if self.recorder.count_presses() > 0:
                self.finish_requested = True
                self.try_finish()
            return "break"
        if self.finish_requested:
            return "break"  # waiting for held keys to be released
        self.recorder.record_press(event.keycode, event.keysym)

    def on_key_release(self, event):
        if event.keysym in ("Return", "KP_Enter"):
            return "break"
        self.recorder.record_release(event.keycode)
        self.try_finish()

    def try_finish(self):
        # Wait until every key is released so the last character's release is captured.
        if self.finish_requested and self.recorder.keys_still_down() == 0:
            self.finish_requested = False
            typed_text = self.entry.get()
            events = list(self.recorder.events)
            self.reset()
            self.on_sample_done(events, typed_text)

    def reset(self):
        self.recorder.reset()
        self.finish_requested = False
        self.entry.delete(0, "end")
        self.entry.focus_set()


# ===============================================================
# Tab 1: Registration
# ===============================================================
class RegisterTab(ttk.Frame):
    def __init__(self, parent, conn):
        ttk.Frame.__init__(self, parent, padding=12)
        self.conn = conn
        self.username = None
        self.collected = []

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Username:").pack(side="left")
        self.username_entry = ttk.Entry(top, width=20)
        self.username_entry.pack(side="left", padx=6)
        ttk.Button(top, text="Start registration", command=self.start_registration).pack(side="left")

        self.status = tk.StringVar(value="Enter a username (3-20 letters/digits/_) and click Start.")
        ttk.Label(self, textvariable=self.status, foreground="#1a4d8f").pack(anchor="w", pady=8)

        self.box = TypingBox(self, self.on_sample_done)
        self.box.pack(fill="x")

        ttk.Label(self, text="Stored profile (mean +/- standard deviation over the registration samples):").pack(
            anchor="w", pady=(12, 2))
        self.profile_text = tk.Text(self, height=14, width=100, state="disabled")
        self.profile_text.pack(fill="both", expand=True)

    def start_registration(self):
        name = self.username_entry.get().strip()
        if not re.match(r"^[A-Za-z0-9_]{3,20}$", name):
            messagebox.showerror("Invalid username", "Use 3-20 letters, digits or underscore.")
            return
        if database.get_user(self.conn, name) is not None:
            replace = messagebox.askyesno(
                "User exists", "'%s' already exists.\nDelete the old profile and ALL its data and re-register?" % name)
            if not replace:
                return
            database.delete_user(self.conn, name)
        self.username = name
        self.collected = []
        self.update_status()
        self.box.reset()

    def update_status(self):
        self.status.set("Registering '%s': sample %d of %d. Type normally; do not rush or slow down." % (
            self.username, len(self.collected) + 1, config.REGISTRATION_SAMPLES))

    def on_sample_done(self, events, typed_text):
        if self.username is None:
            self.status.set("Enter a username and click 'Start registration' first.")
            return
        if typed_text != config.TARGET_TEXT:
            self.status.set("Text did not match - sample NOT counted. Try again (sample %d of %d)." % (
                len(self.collected) + 1, config.REGISTRATION_SAMPLES))
            return
        try:
            features.extract_features(events)  # check the sample can be analysed
        except ValueError as error:
            self.status.set("Sample rejected: %s" % error)
            return

        self.collected.append(events)
        if len(self.collected) < config.REGISTRATION_SAMPLES:
            self.update_status()
            return

        user_id, profile = database.register_user(self.conn, self.username, config.TARGET_TEXT, self.collected)
        self.status.set("Registration complete for '%s'." % self.username)
        self.show_profile(profile)
        messagebox.showinfo("Done", "User '%s' registered with %d samples." % (
            self.username, config.REGISTRATION_SAMPLES))
        self.username = None
        self.collected = []

    def show_profile(self, profile):
        lines = ["Samples used: %d" % profile["num_samples"], ""]
        for name in features.SCALAR_FEATURE_NAMES:
            stats = profile["values"][name]
            lines.append("%-40s %10.2f +/- %8.2f   (min %.1f, max %.1f)" % (
                config.FEATURE_LABELS[name], stats["mean"], stats["sd"], stats["min"], stats["max"]))
        lines.append("")
        lines.append("Key pairs (digraphs) stored: %d" % len(profile["digraphs"]))
        self.profile_text.config(state="normal")
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", "\n".join(lines))
        self.profile_text.config(state="disabled")

    def refresh(self):
        pass


# ===============================================================
# Tab 2: Authentication
# ===============================================================
class AuthenticateTab(ttk.Frame):
    def __init__(self, parent, conn):
        ttk.Frame.__init__(self, parent, padding=12)
        self.conn = conn

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="User:").pack(side="left")
        self.user_box = ttk.Combobox(top, width=20, state="readonly")
        self.user_box.pack(side="left", padx=6)
        ttk.Label(top, text="Show details for:").pack(side="left", padx=(16, 4))
        self.method_choice = tk.StringVar(value="proposed")
        ttk.Radiobutton(top, text="Proposed", variable=self.method_choice, value="proposed").pack(side="left")
        ttk.Radiobutton(top, text="Baseline", variable=self.method_choice, value="baseline").pack(side="left")

        self.box = TypingBox(self, self.on_sample_done)
        self.box.pack(fill="x", pady=8)

        self.headline = tk.Label(self, text="", font=("Helvetica", 22, "bold"))
        self.headline.pack(anchor="w")
        self.summary_line = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.summary_line).pack(anchor="w")

        columns = ("feature", "details", "similarity", "weight", "points")
        self.table = ttk.Treeview(self, columns=columns, show="headings", height=9)
        widths = {"feature": 230, "details": 430, "similarity": 90, "weight": 70, "points": 110}
        titles = {"feature": "Feature", "details": "Your value vs normal", "similarity": "Similarity",
                  "weight": "Weight", "points": "Points"}
        for name in columns:
            self.table.heading(name, text=titles[name])
            self.table.column(name, width=widths[name], anchor="w")
        self.table.pack(fill="x", pady=6)

        self.reason_text = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.reason_text, wraplength=900, justify="left").pack(anchor="w")

        self.last_results = None
        self.method_choice.trace_add("write", lambda *args: self.show_results())

    def refresh(self):
        names = database.list_usernames(self.conn)
        self.user_box["values"] = names
        if len(names) > 0 and self.user_box.get() not in names:
            self.user_box.set(names[0])

    def on_sample_done(self, events, typed_text):
        username = self.user_box.get()
        user = database.get_user(self.conn, username) if username else None
        if user is None:
            messagebox.showerror("No user", "Register a user first, then select them.")
            return
        profile = database.get_profile(self.conn, user["id"])

        text_matches = (typed_text == config.TARGET_TEXT)
        try:
            attempt_features = features.extract_features(events)
        except ValueError as error:
            self.headline.config(text="REJECTED", fg="#b00020")
            self.summary_line.set("Sample could not be analysed: %s" % error)
            return

        results = {}
        for method_name in evaluation.METHOD_NAMES:
            results[method_name] = auth.METHODS[method_name](attempt_features, profile, text_matches)
        self.last_results = results
        self.show_results()

    def show_results(self):
        if self.last_results is None:
            return
        shown = self.last_results[self.method_choice.get()]
        if shown["accepted"]:
            self.headline.config(text="AUTHENTICATED", fg="#1b7f3b")
        else:
            self.headline.config(text="REJECTED", fg="#b00020")

        base = self.last_results["baseline"]
        prop = self.last_results["proposed"]
        self.summary_line.set(
            "%s method: score %.1f / 100 (threshold %.1f)      |      baseline: %s (%.1f)   proposed: %s (%.1f)" % (
                shown["method"].capitalize(), shown["score"], shown["threshold"],
                "ACCEPT" if base["accepted"] else "REJECT", base["score"],
                "ACCEPT" if prop["accepted"] else "REJECT", prop["score"]))

        for row_id in self.table.get_children():
            self.table.delete(row_id)
        for row in shown["rows"]:
            self.table.insert("", "end", values=(
                row["label"], row["detail"], "%.0f%%" % (row["similarity"] * 100.0),
                "%.2f" % row["weight"], "%.1f / %.1f" % (row["points"], row["max_points"])))

        if shown["accepted"]:
            if len(shown["unusual"]) > 0:
                self.reason_text.set("Accepted, but unusual: " + " ; ".join(shown["unusual"]))
            else:
                self.reason_text.set("All features were close to the user's normal typing.")
        else:
            self.reason_text.set("Reasons for rejection:  " + "  |  ".join(shown["reasons"]))


# ===============================================================
# Tab 3: Experiment data collection
# ===============================================================
CATEGORY_INSTRUCTIONS = {
    "genuine_normal": "The genuine user types naturally, as during registration.",
    "genuine_variation": "The genuine user types noticeably FASTER or SLOWER than usual (alternate between them).",
    "impostor_natural": "A DIFFERENT person types naturally. They must not have watched the genuine user type.",
    "impostor_imitation": "A DIFFERENT person tries to copy the genuine user's rhythm. The user's typical speed is shown below as a hint.",
}


class ExperimentTab(ttk.Frame):
    def __init__(self, parent, conn):
        ttk.Frame.__init__(self, parent, padding=12)
        self.conn = conn
        self.label_to_category = {}
        for key, label in config.CATEGORIES.items():
            self.label_to_category[label] = key

        row1 = ttk.Frame(self)
        row1.pack(fill="x")
        ttk.Label(row1, text="Profile owner (genuine user):").pack(side="left")
        self.owner_box = ttk.Combobox(row1, width=18, state="readonly")
        self.owner_box.pack(side="left", padx=6)
        self.owner_box.bind("<<ComboboxSelected>>", lambda event: self.update_info())

        ttk.Label(row1, text="Category:").pack(side="left", padx=(14, 4))
        self.category_box = ttk.Combobox(row1, width=38, state="readonly", values=list(config.CATEGORIES.values()))
        self.category_box.set(config.CATEGORIES["genuine_normal"])
        self.category_box.pack(side="left")
        self.category_box.bind("<<ComboboxSelected>>", lambda event: self.update_info())

        ttk.Label(row1, text="Tester name:").pack(side="left", padx=(14, 4))
        self.tester_entry = ttk.Entry(row1, width=14)
        self.tester_entry.pack(side="left")

        self.instruction = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.instruction, wraplength=900, foreground="#1a4d8f").pack(anchor="w", pady=6)
        self.hint = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.hint, wraplength=900).pack(anchor="w")

        self.box = TypingBox(self, self.on_sample_done)
        self.box.pack(fill="x", pady=8)

        self.message = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.message, font=("Helvetica", 11, "bold")).pack(anchor="w")
        self.counts = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.counts, justify="left").pack(anchor="w", pady=6)

    def current_category(self):
        return self.label_to_category.get(self.category_box.get(), "genuine_normal")

    def refresh(self):
        names = database.list_usernames(self.conn)
        self.owner_box["values"] = names
        if len(names) > 0 and self.owner_box.get() not in names:
            self.owner_box.set(names[0])
        self.update_info()

    def update_info(self):
        category = self.current_category()
        self.instruction.set(CATEGORY_INSTRUCTIONS[category])
        self.hint.set("")
        username = self.owner_box.get()
        user = database.get_user(self.conn, username) if username else None
        if user is None:
            self.counts.set("Register a user first.")
            return
        profile = database.get_profile(self.conn, user["id"])
        if category == "impostor_imitation" and profile is not None:
            speed = profile["values"]["typing_speed_cps"]["mean"]
            total = profile["values"]["total_time_ms"]["mean"] / 1000.0
            self.hint.set("Hint for the imitator: the genuine user types about %.1f chars/sec, "
                          "about %.1f seconds for the whole sentence." % (speed, total))
        counts = database.count_experiment_samples(self.conn, user["id"])
        lines = ["Samples collected against '%s':" % username]
        for key, label in config.CATEGORIES.items():
            lines.append("   %-45s %d" % (label, counts[key]))
        self.counts.set("\n".join(lines))

    def on_sample_done(self, events, typed_text):
        username = self.owner_box.get()
        user = database.get_user(self.conn, username) if username else None
        if user is None:
            self.message.set("Select a registered profile owner first.")
            return
        if typed_text != config.TARGET_TEXT:
            self.message.set("Text did not match - sample NOT saved. Try again.")
            return
        try:
            features.extract_features(events)
        except ValueError as error:
            self.message.set("Sample rejected: %s" % error)
            return
        tester = self.tester_entry.get().strip()
        database.add_experiment_sample(self.conn, user["id"], self.current_category(), tester, events)
        self.message.set("Sample saved.")
        self.update_info()


# ===============================================================
# Tab 4: Results dashboard (Phase 8)
# ===============================================================
class ResultsTab(ttk.Frame):
    POOLED = "All users (pooled)"

    def __init__(self, parent, conn):
        ttk.Frame.__init__(self, parent, padding=12)
        self.conn = conn
        self.results = None

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Evaluate:").pack(side="left")
        self.scope_box = ttk.Combobox(top, width=22, state="readonly")
        self.scope_box.pack(side="left", padx=6)
        ttk.Button(top, text="Run evaluation", command=self.run).pack(side="left", padx=6)
        ttk.Button(top, text="Export CSV", command=self.export).pack(side="left")

        self.note = tk.StringVar(value="Collect samples in the Experiment tab, then click 'Run evaluation'.")
        ttk.Label(self, textvariable=self.note, wraplength=950, foreground="#1a4d8f").pack(anchor="w", pady=6)

        columns = ("metric", "baseline", "proposed")
        self.table = ttk.Treeview(self, columns=columns, show="headings", height=17)
        self.table.heading("metric", text="Metric")
        self.table.heading("baseline", text="Baseline (paper-inspired)")
        self.table.heading("proposed", text="Proposed (multi-feature)")
        self.table.column("metric", width=440, anchor="w")
        self.table.column("baseline", width=190, anchor="center")
        self.table.column("proposed", width=190, anchor="center")
        self.table.pack(fill="x")

        self.canvas = tk.Canvas(self, width=640, height=300, bg="white", highlightthickness=1)
        self.canvas.pack(anchor="w", pady=8)

    def refresh(self):
        names = [self.POOLED] + database.list_usernames(self.conn)
        self.scope_box["values"] = names
        if self.scope_box.get() not in names:
            self.scope_box.set(self.POOLED)

    def run(self):
        scope = self.scope_box.get()
        user_id = None
        if scope != self.POOLED:
            user_id = database.get_user(self.conn, scope)["id"]
        self.results = evaluation.run_evaluation(self.conn, user_id)

        for row_id in self.table.get_children():
            self.table.delete(row_id)
        for metric, base_value, prop_value in evaluation.build_comparison_rows(self.results):
            self.table.insert("", "end", values=(metric, base_value, prop_value))

        base = self.results["baseline"]
        message = "Evaluated %d attempts (%d skipped). " % (len(self.results["records"]), self.results["skipped"])
        if base["genuine_count"] == 0 or base["impostor_count"] == 0:
            message += "Need BOTH genuine and impostor samples to compute FAR/FRR/EER."
        else:
            message += ("EER is found by sweeping the threshold on the same data, so it is optimistic; "
                        "treat results with few samples as indicative only.")
        self.note.set(message)
        self.draw_curves()

    def export(self):
        if self.results is None:
            messagebox.showinfo("Nothing to export", "Run the evaluation first.")
            return
        evaluation.export_csv(self.results)
        messagebox.showinfo("Exported", "Wrote results_summary.csv and results_samples.csv in the project folder.")

    def draw_curves(self):
        """FAR (dashed) and FRR (solid) against threshold. Red = baseline, blue = proposed."""
        canvas = self.canvas
        canvas.delete("all")
        left, top, right, bottom = 50, 20, 620, 250
        canvas.create_rectangle(left, top, right, bottom)
        for percent in (0, 25, 50, 75, 100):
            y = bottom - (bottom - top) * percent / 100.0
            canvas.create_text(left - 6, y, text="%d%%" % percent, anchor="e", font=("Helvetica", 8))
            canvas.create_line(left, y, right, y, fill="#e0e0e0")
        for score in (0, 20, 40, 60, 80, 100):
            x = left + (right - left) * score / 100.0
            canvas.create_text(x, bottom + 10, text=str(score), font=("Helvetica", 8))
        canvas.create_text((left + right) / 2, bottom + 26, text="Score threshold (accept if score >= threshold)",
                           font=("Helvetica", 9))

        colours = {"baseline": "#c62828", "proposed": "#1565c0"}
        legend_x = left
        drew_any = False
        for method_name in evaluation.METHOD_NAMES:
            info = self.results[method_name]["eer_info"]
            if info is None:
                continue
            drew_any = True
            far_points = []
            frr_points = []
            for threshold, far, frr in info["curve"]:
                x = left + (right - left) * threshold / 100.0
                far_points.extend([x, bottom - (bottom - top) * far])
                frr_points.extend([x, bottom - (bottom - top) * frr])
            canvas.create_line(*far_points, fill=colours[method_name], dash=(4, 3), width=2)
            canvas.create_line(*frr_points, fill=colours[method_name], width=2)
            canvas.create_text(legend_x, bottom + 42,
                               text="%s: solid = FRR, dashed = FAR" % method_name, anchor="w",
                               fill=colours[method_name], font=("Helvetica", 9))
            legend_x += 280
        if not drew_any:
            canvas.create_text((left + right) / 2, (top + bottom) / 2,
                               text="No curves yet (need genuine and impostor samples).")


# ===============================================================
# Tab 5: Data viewer (uses view_data.py)
# ===============================================================
class DataTab(ttk.Frame):
    ALL_USERS = "All users"

    def __init__(self, parent, conn):
        ttk.Frame.__init__(self, parent, padding=12)
        self.conn = conn

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Show samples for profile owner:").pack(side="left")
        self.owner_box = ttk.Combobox(top, width=20, state="readonly")
        self.owner_box.pack(side="left", padx=6)
        self.owner_box.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(top, text="Delete selected experiment sample", command=self.delete_selected).pack(side="left")

        ttk.Label(self, text="Summary of experiment samples (owner | category | tester | count):").pack(
            anchor="w", pady=(10, 2))
        self.summary_table = ttk.Treeview(self, columns=("owner", "category", "tester", "count"),
                                          show="headings", height=6)
        for name, title, width in (("owner", "Profile owner", 140), ("category", "Category", 260),
                                   ("tester", "Tester", 140), ("count", "Samples", 80)):
            self.summary_table.heading(name, text=title)
            self.summary_table.column(name, width=width, anchor="w")
        self.summary_table.pack(fill="x")

        ttk.Label(self, text="Every stored sample (select an 'experiment' row to delete it):").pack(
            anchor="w", pady=(10, 2))
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        columns = ("kind", "id", "owner", "category", "tester", "time", "speed", "pauses", "backspaces", "created")
        self.sample_table = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        titles = {"kind": "Kind", "id": "ID", "owner": "Owner", "category": "Category", "tester": "Tester",
                  "time": "Time (ms)", "speed": "Chars/s", "pauses": "Pauses", "backspaces": "Backspaces",
                  "created": "Saved at"}
        widths = {"kind": 90, "id": 45, "owner": 90, "category": 170, "tester": 90, "time": 80,
                  "speed": 65, "pauses": 60, "backspaces": 85, "created": 140}
        for name in columns:
            self.sample_table.heading(name, text=titles[name])
            self.sample_table.column(name, width=widths[name], anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.sample_table.yview)
        self.sample_table.configure(yscrollcommand=scrollbar.set)
        self.sample_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.info = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info).pack(anchor="w", pady=6)

    def refresh(self):
        names = [self.ALL_USERS] + database.list_usernames(self.conn)
        self.owner_box["values"] = names
        if self.owner_box.get() not in names:
            self.owner_box.set(self.ALL_USERS)
        chosen = self.owner_box.get()
        owner = None
        if chosen != self.ALL_USERS:
            owner = chosen

        for row_id in self.summary_table.get_children():
            self.summary_table.delete(row_id)
        for item in view_data.get_experiment_summary(self.conn):
            if owner is None or item["owner"] == owner:
                self.summary_table.insert("", "end", values=(
                    item["owner"], config.CATEGORIES.get(item["category"], item["category"]),
                    item["tester"], item["count"]))

        for row_id in self.sample_table.get_children():
            self.sample_table.delete(row_id)
        samples = view_data.get_sample_list(self.conn, owner)
        for sample in samples:
            numbers = sample["numbers"]
            if numbers is None:
                time_text, speed_text, pause_text, backspace_text = "-", "-", "-", "-"
            else:
                time_text = "%.0f" % numbers["total_time_ms"]
                speed_text = "%.2f" % numbers["speed_cps"]
                pause_text = str(numbers["pauses"])
                backspace_text = str(numbers["backspaces"])
            row_key = "%s-%d" % (sample["kind"], sample["id"])
            self.sample_table.insert("", "end", iid=row_key, values=(
                sample["kind"], sample["id"], sample["owner"],
                config.CATEGORIES.get(sample["category"], sample["category"]), sample["tester"],
                time_text, speed_text, pause_text, backspace_text, sample["created_at"]))
        self.info.set("Showing %d samples. Database file: %s" % (len(samples), config.DB_FILE))

    def delete_selected(self):
        selected = self.sample_table.selection()
        if len(selected) == 0:
            messagebox.showinfo("Nothing selected", "Click an experiment row first.")
            return
        values = self.sample_table.item(selected[0], "values")
        if values[0] != "experiment":
            messagebox.showinfo("Not allowed",
                                "Registration samples cannot be deleted one by one.\n"
                                "Re-register the user in the Register tab instead.")
            return
        if messagebox.askyesno("Delete sample", "Delete experiment sample %s permanently?" % values[1]):
            view_data.delete_experiment_sample(self.conn, int(values[1]))
            self.refresh()


# ===============================================================
# Main window
# ===============================================================
def main():
    conn = database.connect()
    database.create_tables(conn)

    root = tk.Tk()
    root.title("Keystroke Dynamics Authentication - Baseline vs Multi-feature")
    root.geometry("1020x820")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    tabs = [
        ("1. Register", RegisterTab(notebook, conn)),
        ("2. Authenticate", AuthenticateTab(notebook, conn)),
        ("3. Experiment", ExperimentTab(notebook, conn)),
        ("4. Results", ResultsTab(notebook, conn)),
        ("5. Data", DataTab(notebook, conn)),
    ]
    for title, tab in tabs:
        notebook.add(tab, text=title)

    def on_tab_changed(event):
        selected = notebook.nametowidget(notebook.select())
        selected.refresh()

    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
    root.mainloop()


if __name__ == "__main__":
    main()
