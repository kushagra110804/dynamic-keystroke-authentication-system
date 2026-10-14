"""
view_data.py

Read-only helpers to look at what is stored in keystroke.db.
Used in two ways:
  1. Command line:   python view_data.py            (or: python view_data.py other.db)
  2. Inside the app: the "5. Data" tab in app.py imports these functions.

The only function that CHANGES data is delete_experiment_sample().
Registration samples cannot be deleted one by one, because that would
break the 10-sample profile; re-register the user instead.
"""

import sys

import database
import features


def get_user_summary(conn):
    """One dict per user: how many registration and experiment samples they have."""
    sql = (
        "SELECT u.username, u.created_at, "
        "  (SELECT COUNT(*) FROM registration_samples r WHERE r.user_id = u.id) AS reg_count, "
        "  (SELECT COUNT(*) FROM experiment_samples e WHERE e.user_id = u.id) AS exp_count "
        "FROM users u ORDER BY u.username"
    )
    summary = []
    for row in conn.execute(sql).fetchall():
        summary.append({
            "username": row["username"],
            "created_at": row["created_at"],
            "registration_samples": row["reg_count"],
            "experiment_samples": row["exp_count"],
        })
    return summary


def get_experiment_summary(conn):
    """Counts of experiment samples per profile owner, category and tester."""
    sql = (
        "SELECT u.username AS owner, e.category, e.tester_name, COUNT(*) AS n "
        "FROM experiment_samples e JOIN users u ON u.id = e.user_id "
        "GROUP BY u.username, e.category, e.tester_name "
        "ORDER BY u.username, e.category, e.tester_name"
    )
    summary = []
    for row in conn.execute(sql).fetchall():
        summary.append({
            "owner": row["owner"],
            "category": row["category"],
            "tester": row["tester_name"] or "",
            "count": row["n"],
        })
    return summary


def quick_numbers(events):
    """Total time, speed, pauses and backspaces of one sample, or None if unreadable."""
    try:
        extracted = features.extract_features(events)
    except ValueError:
        return None
    values = extracted["values"]
    return {
        "total_time_ms": values["total_time_ms"],
        "speed_cps": values["typing_speed_cps"],
        "pauses": int(values["pause_count"]),
        "backspaces": int(values["backspace_count"]),
    }


def get_sample_list(conn, owner=None):
    """
    Every stored sample (registration and experiment), newest last.
    Each item: kind ('registration' or 'experiment'), id, owner, category,
    tester, created_at, and quick numbers (or None).
    """
    import json
    items = []

    sql = ("SELECT r.id, u.username, r.sample_no, r.events_json, r.created_at "
           "FROM registration_samples r JOIN users u ON u.id = r.user_id")
    parameters = ()
    if owner is not None:
        sql += " WHERE u.username = ?"
        parameters = (owner,)
    sql += " ORDER BY r.id"
    for row in conn.execute(sql, parameters).fetchall():
        items.append({
            "kind": "registration", "id": row["id"], "owner": row["username"],
            "category": "registration #%d" % row["sample_no"], "tester": row["username"],
            "created_at": row["created_at"],
            "numbers": quick_numbers(json.loads(row["events_json"])),
        })

    sql = ("SELECT e.id, u.username, e.category, e.tester_name, e.events_json, e.created_at "
           "FROM experiment_samples e JOIN users u ON u.id = e.user_id")
    if owner is not None:
        sql += " WHERE u.username = ?"
    sql += " ORDER BY e.id"
    for row in conn.execute(sql, parameters).fetchall():
        items.append({
            "kind": "experiment", "id": row["id"], "owner": row["username"],
            "category": row["category"], "tester": row["tester_name"] or "",
            "created_at": row["created_at"],
            "numbers": quick_numbers(json.loads(row["events_json"])),
        })
    return items


def delete_experiment_sample(conn, sample_id):
    """Remove one wrongly recorded experiment sample (for example a mislabelled one)."""
    conn.execute("DELETE FROM experiment_samples WHERE id = ?", (sample_id,))
    conn.commit()


# ---------------------------------------------------------------
# Command-line report
# ---------------------------------------------------------------
def print_report(conn):
    print("=" * 78)
    print("USERS")
    print("=" * 78)
    users = get_user_summary(conn)
    if len(users) == 0:
        print("  (no users registered yet)")
    for user in users:
        print("  %-16s registration samples: %-3d experiment samples: %-4d created: %s" % (
            user["username"], user["registration_samples"], user["experiment_samples"], user["created_at"]))

    print()
    print("=" * 78)
    print("EXPERIMENT SAMPLES  (profile owner | category | tester | count)")
    print("=" * 78)
    experiment = get_experiment_summary(conn)
    if len(experiment) == 0:
        print("  (no experiment samples yet)")
    for item in experiment:
        print("  %-14s | %-20s | %-12s | %d" % (item["owner"], item["category"], item["tester"], item["count"]))

    print()
    print("=" * 78)
    print("EVERY SAMPLE")
    print("=" * 78)
    print("  %-12s %-5s %-12s %-20s %-10s %9s %6s %6s %5s" % (
        "kind", "id", "owner", "category", "tester", "time(ms)", "cps", "pause", "bksp"))
    for sample in get_sample_list(conn):
        numbers = sample["numbers"]
        if numbers is None:
            numbers_text = "   (could not analyse)"
        else:
            numbers_text = "%9.0f %6.2f %6d %5d" % (
                numbers["total_time_ms"], numbers["speed_cps"], numbers["pauses"], numbers["backspaces"])
        print("  %-12s %-5d %-12s %-20s %-10s %s" % (
            sample["kind"], sample["id"], sample["owner"], sample["category"], sample["tester"], numbers_text))


if __name__ == "__main__":
    db_file = None
    if len(sys.argv) > 1:
        db_file = sys.argv[1]
    connection = database.connect(db_file)
    database.create_tables(connection)
    print_report(connection)
