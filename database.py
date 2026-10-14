"""
database.py   (Phase 4)

SQLite storage. Three tables:

  users                 one row per registered user, with the stored profile (JSON)
  registration_samples  the raw events of each of the user's registration samples
  experiment_samples    raw events of test attempts used in the evaluation,
                        labelled with a category (genuine / impostor ...)

Only RAW events are stored for samples. Features are recomputed when needed,
so changing a setting in config.py (e.g. the pause threshold) never leaves
stale numbers behind. Run  python database.py rebuild  to rebuild profiles.
"""

import json
import sqlite3
import sys
from datetime import datetime

import config
import features


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect(db_file=None):
    if db_file is None:
        db_file = config.DB_FILE
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL,
            target_text  TEXT NOT NULL,
            profile_json TEXT,
            created_at   TEXT NOT NULL
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registration_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            sample_no   INTEGER NOT NULL,
            events_json TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS experiment_samples (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category    TEXT NOT NULL,
            tester_name TEXT,
            events_json TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )""")
    conn.commit()


# ---------------------------------------------------------------
# Users and profiles
# ---------------------------------------------------------------
def get_user(conn, username):
    """Returns the user row or None."""
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def list_usernames(conn):
    rows = conn.execute("SELECT username FROM users ORDER BY username").fetchall()
    names = []
    for row in rows:
        names.append(row["username"])
    return names


def register_user(conn, username, target_text, samples_events):
    """
    Create a user from a list of samples (each sample = a raw events list).
    Computes the profile and stores everything in one transaction.
    Returns (user_id, profile).
    """
    feature_list = []
    for events in samples_events:
        feature_list.append(features.extract_features(events))
    profile = features.build_profile(feature_list)

    try:
        cursor = conn.execute(
            "INSERT INTO users (username, target_text, profile_json, created_at) VALUES (?, ?, ?, ?)",
            (username, target_text, json.dumps(profile), now_text()),
        )
        user_id = cursor.lastrowid
        sample_no = 1
        for events in samples_events:
            conn.execute(
                "INSERT INTO registration_samples (user_id, sample_no, events_json, created_at) VALUES (?, ?, ?, ?)",
                (user_id, sample_no, json.dumps(events), now_text()),
            )
            sample_no += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return user_id, profile


def get_profile(conn, user_id):
    row = conn.execute("SELECT profile_json FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["profile_json"] is None:
        return None
    return json.loads(row["profile_json"])


def delete_user(conn, username):
    """Deletes the user and (via ON DELETE CASCADE) all their samples."""
    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()


def rebuild_profile(conn, user_id):
    """Recompute and store a user's profile from their stored registration samples."""
    rows = conn.execute(
        "SELECT events_json FROM registration_samples WHERE user_id = ? ORDER BY sample_no",
        (user_id,),
    ).fetchall()
    feature_list = []
    for row in rows:
        feature_list.append(features.extract_features(json.loads(row["events_json"])))
    profile = features.build_profile(feature_list)
    conn.execute("UPDATE users SET profile_json = ? WHERE id = ?", (json.dumps(profile), user_id))
    conn.commit()
    return profile


# ---------------------------------------------------------------
# Experiment samples
# ---------------------------------------------------------------
def add_experiment_sample(conn, user_id, category, tester_name, events):
    conn.execute(
        "INSERT INTO experiment_samples (user_id, category, tester_name, events_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, category, tester_name, json.dumps(events), now_text()),
    )
    conn.commit()


def get_experiment_samples(conn, user_id=None):
    """All experiment samples (or only those tested against one user's profile)."""
    sql = ("SELECT e.id, e.user_id, u.username, e.category, e.tester_name, e.events_json "
           "FROM experiment_samples e JOIN users u ON u.id = e.user_id")
    parameters = ()
    if user_id is not None:
        sql += " WHERE e.user_id = ?"
        parameters = (user_id,)
    sql += " ORDER BY e.id"

    samples = []
    for row in conn.execute(sql, parameters).fetchall():
        samples.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "category": row["category"],
            "tester_name": row["tester_name"],
            "events": json.loads(row["events_json"]),
        })
    return samples


def count_experiment_samples(conn, user_id):
    """Returns {category: count} for one profile owner."""
    counts = {}
    for category in config.CATEGORIES:
        counts[category] = 0
    rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM experiment_samples WHERE user_id = ? GROUP BY category",
        (user_id,),
    ).fetchall()
    for row in rows:
        counts[row["category"]] = row["n"]
    return counts


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        connection = connect()
        create_tables(connection)
        for row in connection.execute("SELECT id, username FROM users").fetchall():
            rebuild_profile(connection, row["id"])
            print("Rebuilt profile for", row["username"])
    else:
        print("Usage: python database.py rebuild")
