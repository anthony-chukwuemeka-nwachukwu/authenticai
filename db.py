"""
db.py — SQLite persistence for AuthenticAI (multi-tenant).

All tables are scoped by institution_id. Queries always filter by institution.

Schema
------
institutions  : id, name, code (unique), created_at
users         : id, username, password_hash, security_question,
                security_answer_hash, role, institution_id, created_at
students      : id, name, institution_id
submissions   : id, student_id, institution_id, course_code, text,
                features, alpha_q, alpha_s, verdict, explanation,
                status, created_at, profile_before, profile_after
profiles      : student_id, institution_id, psi_cell, psi_hidden,
                psi_forget, window_w, window_w_tau, updated_at
temp_profiles : sub_id, psi_cell, psi_hidden, psi_forget,
                window_w, window_w_tau, created_at

Roles
-----
superadmin — no institution scope, sees everything
admin      — institution-scoped admin
lecturer   — institution-scoped, read/submit only
"""

import sqlite3, json, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "authenticai.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allows concurrent reads + writes
    conn.execute("PRAGMA busy_timeout=30000") # wait up to 30s if locked
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS institutions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        code       TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        username             TEXT NOT NULL UNIQUE,
        password_hash        TEXT NOT NULL,
        security_question    TEXT NOT NULL,
        security_answer_hash TEXT NOT NULL,
        role                 TEXT NOT NULL DEFAULT 'lecturer',
        institution_id       INTEGER,
        created_at           TEXT NOT NULL,
        FOREIGN KEY (institution_id) REFERENCES institutions(id)
    );

    CREATE TABLE IF NOT EXISTS students (
        id             TEXT NOT NULL,
        name           TEXT NOT NULL,
        institution_id INTEGER NOT NULL,
        type_counts    TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (id, institution_id)
    );

    CREATE TABLE IF NOT EXISTS submissions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id      TEXT NOT NULL,
        institution_id  INTEGER NOT NULL,
        course_code     TEXT NOT NULL,
        text            TEXT NOT NULL,
        features        TEXT,
        alpha_q         REAL,
        alpha_s         REAL,
        verdict         TEXT,
        explanation     TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        created_at      TEXT NOT NULL,
        profile_before  TEXT,
        profile_after   TEXT
    );

    CREATE TABLE IF NOT EXISTS profiles (
        student_id     TEXT NOT NULL,
        institution_id INTEGER NOT NULL,
        psi_cell       TEXT,
        psi_hidden     TEXT NOT NULL DEFAULT '{}',
        psi_forget     TEXT,
        window_w       TEXT NOT NULL DEFAULT '{}',
        window_w_tau   TEXT NOT NULL DEFAULT '{}',
        updated_at     TEXT NOT NULL,
        PRIMARY KEY (student_id, institution_id)
    );

    CREATE TABLE IF NOT EXISTS courses (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        code           TEXT NOT NULL,
        name           TEXT NOT NULL,
        institution_id INTEGER NOT NULL,
        created_at     TEXT NOT NULL,
        UNIQUE (code, institution_id)
    );

    CREATE TABLE IF NOT EXISTS temp_profiles (
        sub_id       INTEGER PRIMARY KEY,
        psi_cell     TEXT,
        psi_hidden   TEXT NOT NULL DEFAULT '{}',
        psi_forget   TEXT,
        window_w     TEXT NOT NULL DEFAULT '{}',
        window_w_tau TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


# ── Institutions ──────────────────────────────────────────────────────────────

def get_institution_by_code(code):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM institutions WHERE code = ?", (code,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_institution_by_id(inst_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM institutions WHERE id = ?", (inst_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_institution(name, code):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO institutions (name, code, created_at) VALUES (?, ?, ?)",
            (name, code, datetime.utcnow().isoformat())
        )
        inst_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        return inst_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def get_all_institutions():
    conn = get_conn()
    rows = conn.execute(
        "SELECT i.*, COUNT(u.id) as user_count "
        "FROM institutions i LEFT JOIN users u ON u.institution_id = i.id "
        "GROUP BY i.id ORDER BY i.created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Students (institution-scoped) ─────────────────────────────────────────────

def get_students(institution_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name FROM students WHERE institution_id = ? ORDER BY name",
        (institution_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_student(student_id, institution_id):
    """Remove a student and all their data from the institution."""
    conn = get_conn()
    conn.execute("DELETE FROM submissions WHERE student_id=? AND institution_id=?",
                 (student_id, institution_id))
    conn.execute("DELETE FROM profiles WHERE student_id=? AND institution_id=?",
                 (student_id, institution_id))
    conn.execute("DELETE FROM students WHERE id=? AND institution_id=?",
                 (student_id, institution_id))
    conn.commit()
    conn.close()


def ensure_student(student_id, institution_id, name=None):
    display_name = name or student_id
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO students (id, name, institution_id) VALUES (?, ?, ?)",
        (student_id, display_name, institution_id)
    )
    if name:
        conn.execute(
            "UPDATE students SET name = ? WHERE id = ? AND institution_id = ?",
            (display_name, student_id, institution_id)
        )
    conn.commit()
    conn.close()


# ── Profiles (institution-scoped) ─────────────────────────────────────────────

def get_profile(student_id, institution_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM profiles WHERE student_id = ? AND institution_id = ?",
        (student_id, institution_id)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    p = dict(row)
    psi_hidden = json.loads(p["psi_hidden"])
    # Remove literal "course_code" key — artefact from early LLM prompt bug
    psi_hidden.pop("course_code", None)
    p["psi_hidden"]   = psi_hidden
    p["window_w"]     = json.loads(p["window_w"])
    p["window_w_tau"] = json.loads(p["window_w_tau"])
    return p


def save_profile(student_id, institution_id, psi_cell, psi_hidden,
                 psi_forget, window_w, window_w_tau):
    conn = get_conn()
    conn.execute("""
        INSERT INTO profiles
            (student_id, institution_id, psi_cell, psi_hidden, psi_forget,
             window_w, window_w_tau, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, institution_id) DO UPDATE SET
            psi_cell     = excluded.psi_cell,
            psi_hidden   = excluded.psi_hidden,
            psi_forget   = excluded.psi_forget,
            window_w     = excluded.window_w,
            window_w_tau = excluded.window_w_tau,
            updated_at   = excluded.updated_at
    """, (
        student_id, institution_id, psi_cell,
        json.dumps(psi_hidden), psi_forget,
        json.dumps(window_w), json.dumps(window_w_tau),
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()


# ── Submissions (institution-scoped) ──────────────────────────────────────────

def save_submission(student_id, institution_id, course_code, text, features,
                    alpha_q, alpha_s, verdict, explanation, status,
                    profile_before=None, profile_after=None):
    def _safe(v):
        """Ensure v is a SQLite-compatible scalar — serialise dicts/lists."""
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        if v is None:
            return None
        return str(v) if not isinstance(v, (int, float, str, bytes)) else v

    conn = get_conn()
    # Resolve institution_id — may arrive as string from form
    try:
        institution_id = int(institution_id)
    except (TypeError, ValueError):
        institution_id = 0

    conn.execute("""
        INSERT INTO submissions
            (student_id, institution_id, course_code, text, features,
             alpha_q, alpha_s, verdict, explanation, status, created_at,
             profile_before, profile_after)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(student_id), institution_id, str(course_code), str(text),
        json.dumps(features), float(alpha_q), float(alpha_s),
        _safe(verdict), _safe(explanation), str(status),
        datetime.utcnow().isoformat(),
        json.dumps(profile_before) if profile_before else None,
        json.dumps(profile_after)  if profile_after  else None,
    ))
    sub_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return sub_id


def get_submission(sub_id, institution_id=None):
    conn = get_conn()
    if institution_id:
        row = conn.execute(
            "SELECT * FROM submissions WHERE id = ? AND institution_id = ?",
            (sub_id, institution_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (sub_id,)
        ).fetchone()
    conn.close()
    if row is None:
        return None
    s = dict(row)
    s["features"]       = json.loads(s["features"]) if s["features"] else {}
    s["profile_before"] = json.loads(s["profile_before"]) if s.get("profile_before") else None
    s["profile_after"]  = json.loads(s["profile_after"])  if s.get("profile_after")  else None
    return s


def get_submissions_for_student(student_id, institution_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, course_code, alpha_q, alpha_s, verdict, status, created_at
        FROM submissions
        WHERE student_id = ? AND institution_id = ?
        ORDER BY created_at DESC
    """, (student_id, institution_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_submissions(student_id, institution_id):
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE student_id = ? AND institution_id = ?",
        (student_id, institution_id)
    ).fetchone()[0]
    conn.close()
    return n


def count_submissions_by_type(student_id, institution_id, course_code):
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) FROM submissions "
        "WHERE student_id = ? AND institution_id = ? AND course_code = ?",
        (student_id, institution_id, course_code)
    ).fetchone()[0]
    conn.close()
    return n


def update_submission_status(sub_id, status):
    conn = get_conn()
    conn.execute("UPDATE submissions SET status = ? WHERE id = ?", (status, sub_id))
    conn.commit()
    conn.close()


def get_pending_flags(institution_id=None, student_id=None):
    conn = get_conn()
    if institution_id and student_id:
        rows = conn.execute("""
            SELECT s.*, st.name as student_name
            FROM submissions s JOIN students st
              ON s.student_id = st.id AND s.institution_id = st.institution_id
            WHERE s.status = 'flagged'
              AND s.institution_id = ? AND s.student_id = ?
            ORDER BY s.created_at DESC
        """, (institution_id, student_id)).fetchall()
    elif institution_id:
        rows = conn.execute("""
            SELECT s.*, st.name as student_name
            FROM submissions s JOIN students st
              ON s.student_id = st.id AND s.institution_id = st.institution_id
            WHERE s.status = 'flagged' AND s.institution_id = ?
            ORDER BY s.created_at DESC
        """, (institution_id,)).fetchall()
    else:
        # superadmin — all institutions
        rows = conn.execute("""
            SELECT s.*, st.name as student_name, i.name as institution_name
            FROM submissions s
            JOIN students st ON s.student_id = st.id AND s.institution_id = st.institution_id
            JOIN institutions i ON s.institution_id = i.id
            WHERE s.status = 'flagged'
            ORDER BY s.created_at DESC
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Courses (institution-scoped) ─────────────────────────────────────────────

def get_courses(institution_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, code, name FROM courses WHERE institution_id = ? ORDER BY code",
        (institution_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_course(code, name, institution_id):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO courses (code, name, institution_id, created_at) VALUES (?, ?, ?, ?)",
            (code.strip().upper(), name.strip(), institution_id,
             __import__('datetime').datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return True, None
    except __import__('sqlite3').IntegrityError:
        conn.close()
        return False, f"Course code '{code.upper()}' already exists in this institution."


def delete_course(course_id, institution_id):
    conn = get_conn()
    conn.execute(
        "DELETE FROM courses WHERE id = ? AND institution_id = ?",
        (course_id, institution_id)
    )
    conn.commit()
    conn.close()


# ── Temp profiles ─────────────────────────────────────────────────────────────

def save_temp_profile(sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO temp_profiles
            (sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (sub_id, psi_cell, json.dumps(psi_hidden),
          psi_forget, json.dumps(window_w), json.dumps(window_w_tau),
          datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def load_temp_profile(sub_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM temp_profiles WHERE sub_id = ?", (sub_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    p = dict(row)
    p["psi_hidden"]   = json.loads(p["psi_hidden"])
    p["window_w"]     = json.loads(p["window_w"])
    p["window_w_tau"] = json.loads(p["window_w_tau"])
    return p


def delete_temp_profile(sub_id):
    conn = get_conn()
    conn.execute("DELETE FROM temp_profiles WHERE sub_id = ?", (sub_id,))
    conn.commit()
    conn.close()
