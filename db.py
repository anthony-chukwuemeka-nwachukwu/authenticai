"""
db.py — Persistence for AuthenticAI (multi-tenant).

Supports SQLite (local dev) and PostgreSQL (Azure production).
Set AZURE_POSTGRESQL_CONNECTIONSTRING env var to use PostgreSQL.
All tables are scoped by institution_id.
"""

import json, os
from datetime import datetime

# ── Connection ────────────────────────────────────────────────────────────────

PG_CONN_STR = os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING", "")
USE_PG = bool(PG_CONN_STR)


def get_conn():
    if USE_PG:
        import psycopg2
        import psycopg2.extras
        # Parse Azure connection string format:
        # host=... port=... dbname=... user=... password=... sslmode=require
        conn = psycopg2.connect(PG_CONN_STR)
        conn.autocommit = False
        return conn
    else:
        import sqlite3
        DB_PATH = os.path.join(os.path.dirname(__file__), "authenticai.db")
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn


def _ph():
    """Return the correct placeholder for the current DB."""
    return "%s" if USE_PG else "?"


def _row_to_dict(row):
    """Convert a DB row to dict regardless of DB type."""
    if row is None:
        return None
    if USE_PG:
        return dict(row)
    return dict(row)


def _fetchone(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    if USE_PG:
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    return dict(row)


def _fetchall(cursor):
    rows = cursor.fetchall()
    if USE_PG:
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    return [dict(row) for row in rows]


def _execute(conn, sql, params=None):
    """Execute with correct placeholder style."""
    if USE_PG:
        sql = sql.replace("?", "%s")
    c = conn.cursor()
    if params:
        c.execute(sql, params)
    else:
        c.execute(sql)
    return c


def _lastrowid(conn, cursor, table):
    """Get last inserted row ID."""
    if USE_PG:
        cursor.execute(f"SELECT lastval()")
        return cursor.fetchone()[0]
    return cursor.lastrowid


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_conn()
    c = conn.cursor()

    if USE_PG:
        statements = [
            """CREATE TABLE IF NOT EXISTS institutions (
                id         SERIAL PRIMARY KEY,
                name       TEXT NOT NULL,
                code       TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS users (
                id                   SERIAL PRIMARY KEY,
                username             TEXT NOT NULL UNIQUE,
                password_hash        TEXT NOT NULL,
                security_question    TEXT NOT NULL,
                security_answer_hash TEXT NOT NULL,
                role                 TEXT NOT NULL DEFAULT 'lecturer',
                institution_id       INTEGER,
                created_at           TEXT NOT NULL,
                FOREIGN KEY (institution_id) REFERENCES institutions(id)
            )""",
            """CREATE TABLE IF NOT EXISTS students (
                id             TEXT NOT NULL,
                name           TEXT NOT NULL,
                institution_id INTEGER NOT NULL,
                type_counts    TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (id, institution_id)
            )""",
            """CREATE TABLE IF NOT EXISTS submissions (
                id              SERIAL PRIMARY KEY,
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
            )""",
            """CREATE TABLE IF NOT EXISTS profiles (
                student_id     TEXT NOT NULL,
                institution_id INTEGER NOT NULL,
                psi_cell       TEXT,
                psi_hidden     TEXT NOT NULL DEFAULT '{}',
                psi_forget     TEXT,
                window_w       TEXT NOT NULL DEFAULT '{}',
                window_w_tau   TEXT NOT NULL DEFAULT '{}',
                updated_at     TEXT NOT NULL,
                PRIMARY KEY (student_id, institution_id)
            )""",
            """CREATE TABLE IF NOT EXISTS courses (
                id             SERIAL PRIMARY KEY,
                code           TEXT NOT NULL,
                name           TEXT NOT NULL,
                institution_id INTEGER NOT NULL,
                created_at     TEXT NOT NULL,
                UNIQUE (code, institution_id)
            )""",
            """CREATE TABLE IF NOT EXISTS temp_profiles (
                sub_id       INTEGER PRIMARY KEY,
                psi_cell     TEXT,
                psi_hidden   TEXT NOT NULL DEFAULT '{}',
                psi_forget   TEXT,
                window_w     TEXT NOT NULL DEFAULT '{}',
                window_w_tau TEXT NOT NULL DEFAULT '{}',
                created_at   TEXT NOT NULL
            )""",
        ]
        for stmt in statements:
            c.execute(stmt)
    else:
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
    c = _execute(conn, "SELECT * FROM institutions WHERE code = ?", (code,))
    row = _fetchone(c)
    conn.close()
    return row


def get_institution_by_id(inst_id):
    conn = get_conn()
    c = _execute(conn, "SELECT * FROM institutions WHERE id = ?", (inst_id,))
    row = _fetchone(c)
    conn.close()
    return row


def create_institution(name, code):
    conn = get_conn()
    try:
        if USE_PG:
            c = conn.cursor()
            c.execute(
                "INSERT INTO institutions (name, code, created_at) VALUES (%s, %s, %s) RETURNING id",
                (name, code, datetime.utcnow().isoformat())
            )
            inst_id = c.fetchone()[0]
        else:
            c = _execute(conn,
                "INSERT INTO institutions (name, code, created_at) VALUES (?, ?, ?)",
                (name, code, datetime.utcnow().isoformat())
            )
            inst_id = c.lastrowid
        conn.commit()
        conn.close()
        return inst_id
    except Exception:
        conn.close()
        return None


def get_all_institutions():
    conn = get_conn()
    c = _execute(conn,
        "SELECT i.*, COUNT(u.id) as user_count "
        "FROM institutions i LEFT JOIN users u ON u.institution_id = i.id "
        "GROUP BY i.id ORDER BY i.created_at"
    )
    rows = _fetchall(c)
    conn.close()
    return rows


# ── Students ──────────────────────────────────────────────────────────────────

def get_students(institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT id, name FROM students WHERE institution_id = ? ORDER BY name",
        (institution_id,)
    )
    rows = _fetchall(c)
    conn.close()
    return rows


def ensure_student(student_id, institution_id, name=None):
    display_name = name or student_id
    conn = get_conn()
    if USE_PG:
        conn.cursor().execute(
            "INSERT INTO students (id, name, institution_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (id, institution_id) DO UPDATE SET name = EXCLUDED.name",
            (student_id, display_name, institution_id)
        )
    else:
        _execute(conn,
            "INSERT OR IGNORE INTO students (id, name, institution_id) VALUES (?, ?, ?)",
            (student_id, display_name, institution_id)
        )
        if name:
            _execute(conn,
                "UPDATE students SET name = ? WHERE id = ? AND institution_id = ?",
                (display_name, student_id, institution_id)
            )
    conn.commit()
    conn.close()


def delete_student(student_id, institution_id):
    conn = get_conn()
    _execute(conn, "DELETE FROM submissions WHERE student_id=? AND institution_id=?",
             (student_id, institution_id))
    _execute(conn, "DELETE FROM profiles WHERE student_id=? AND institution_id=?",
             (student_id, institution_id))
    _execute(conn, "DELETE FROM students WHERE id=? AND institution_id=?",
             (student_id, institution_id))
    conn.commit()
    conn.close()


# ── Profiles ──────────────────────────────────────────────────────────────────

def get_profile(student_id, institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT * FROM profiles WHERE student_id = ? AND institution_id = ?",
        (student_id, institution_id)
    )
    row = _fetchone(c)
    conn.close()
    if row is None:
        return None
    psi_hidden = json.loads(row["psi_hidden"])
    psi_hidden.pop("course_code", None)
    row["psi_hidden"]   = psi_hidden
    row["window_w"]     = json.loads(row["window_w"])
    row["window_w_tau"] = json.loads(row["window_w_tau"])
    return row


def save_profile(student_id, institution_id, psi_cell, psi_hidden,
                 psi_forget, window_w, window_w_tau):
    conn = get_conn()
    if USE_PG:
        conn.cursor().execute("""
            INSERT INTO profiles
                (student_id, institution_id, psi_cell, psi_hidden, psi_forget,
                 window_w, window_w_tau, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (student_id, institution_id) DO UPDATE SET
                psi_cell     = EXCLUDED.psi_cell,
                psi_hidden   = EXCLUDED.psi_hidden,
                psi_forget   = EXCLUDED.psi_forget,
                window_w     = EXCLUDED.window_w,
                window_w_tau = EXCLUDED.window_w_tau,
                updated_at   = EXCLUDED.updated_at
        """, (
            student_id, institution_id, psi_cell,
            json.dumps(psi_hidden), psi_forget,
            json.dumps(window_w), json.dumps(window_w_tau),
            datetime.utcnow().isoformat()
        ))
    else:
        _execute(conn, """
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


# ── Submissions ───────────────────────────────────────────────────────────────

def save_submission(student_id, institution_id, course_code, text, features,
                    alpha_q, alpha_s, verdict, explanation, status,
                    profile_before=None, profile_after=None):
    def _safe(v):
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        if v is None:
            return None
        return str(v) if not isinstance(v, (int, float, str, bytes)) else v

    try:
        institution_id = int(institution_id)
    except (TypeError, ValueError):
        institution_id = 0

    conn = get_conn()
    if USE_PG:
        c = conn.cursor()
        c.execute("""
            INSERT INTO submissions
                (student_id, institution_id, course_code, text, features,
                 alpha_q, alpha_s, verdict, explanation, status, created_at,
                 profile_before, profile_after)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            str(student_id), institution_id, str(course_code), str(text),
            json.dumps(features), float(alpha_q), float(alpha_s),
            _safe(verdict), _safe(explanation), str(status),
            datetime.utcnow().isoformat(),
            json.dumps(profile_before) if profile_before else None,
            json.dumps(profile_after)  if profile_after  else None,
        ))
        sub_id = c.fetchone()[0]
    else:
        c = _execute(conn, """
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
        sub_id = c.lastrowid
    conn.commit()
    conn.close()
    return sub_id


def get_submission(sub_id, institution_id=None):
    conn = get_conn()
    if institution_id:
        c = _execute(conn,
            "SELECT * FROM submissions WHERE id = ? AND institution_id = ?",
            (sub_id, institution_id)
        )
    else:
        c = _execute(conn, "SELECT * FROM submissions WHERE id = ?", (sub_id,))
    row = _fetchone(c)
    conn.close()
    if row is None:
        return None
    row["features"]       = json.loads(row["features"]) if row["features"] else {}
    row["profile_before"] = json.loads(row["profile_before"]) if row.get("profile_before") else None
    row["profile_after"]  = json.loads(row["profile_after"])  if row.get("profile_after")  else None
    return row


def get_submissions_for_student(student_id, institution_id):
    conn = get_conn()
    c = _execute(conn, """
        SELECT id, course_code, alpha_q, alpha_s, verdict, status, created_at
        FROM submissions
        WHERE student_id = ? AND institution_id = ?
        ORDER BY created_at DESC
    """, (student_id, institution_id))
    rows = _fetchall(c)
    conn.close()
    return rows


def count_submissions(student_id, institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT COUNT(*) FROM submissions WHERE student_id = ? AND institution_id = ?",
        (student_id, institution_id)
    )
    n = c.fetchone()[0]
    conn.close()
    return n


def count_submissions_by_type(student_id, institution_id, course_code):
    conn = get_conn()
    c = _execute(conn,
        "SELECT COUNT(*) FROM submissions "
        "WHERE student_id = ? AND institution_id = ? AND course_code = ?",
        (student_id, institution_id, course_code)
    )
    n = c.fetchone()[0]
    conn.close()
    return n


def update_submission_status(sub_id, status):
    conn = get_conn()
    _execute(conn, "UPDATE submissions SET status = ? WHERE id = ?", (status, sub_id))
    conn.commit()
    conn.close()


def get_pending_flags(institution_id=None, student_id=None):
    conn = get_conn()
    if institution_id and student_id:
        c = _execute(conn, """
            SELECT s.*, st.name as student_name
            FROM submissions s JOIN students st
              ON s.student_id = st.id AND s.institution_id = st.institution_id
            WHERE s.status = 'flagged'
              AND s.institution_id = ? AND s.student_id = ?
            ORDER BY s.created_at DESC
        """, (institution_id, student_id))
    elif institution_id:
        c = _execute(conn, """
            SELECT s.*, st.name as student_name
            FROM submissions s JOIN students st
              ON s.student_id = st.id AND s.institution_id = st.institution_id
            WHERE s.status = 'flagged' AND s.institution_id = ?
            ORDER BY s.created_at DESC
        """, (institution_id,))
    else:
        c = _execute(conn, """
            SELECT s.*, st.name as student_name, i.name as institution_name
            FROM submissions s
            JOIN students st ON s.student_id = st.id AND s.institution_id = st.institution_id
            JOIN institutions i ON s.institution_id = i.id
            WHERE s.status = 'flagged'
            ORDER BY s.created_at DESC
        """)
    rows = _fetchall(c)
    conn.close()
    return rows


# ── Courses ───────────────────────────────────────────────────────────────────

def get_courses(institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT id, code, name FROM courses WHERE institution_id = ? ORDER BY code",
        (institution_id,)
    )
    rows = _fetchall(c)
    conn.close()
    return rows


def add_course(code, name, institution_id):
    conn = get_conn()
    try:
        _execute(conn,
            "INSERT INTO courses (code, name, institution_id, created_at) VALUES (?, ?, ?, ?)",
            (code.strip().upper(), name.strip(), institution_id,
             datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
        return True, None
    except Exception as e:
        conn.close()
        return False, f"Course code '{code.upper()}' already exists in this institution."


def delete_course(course_id, institution_id):
    conn = get_conn()
    _execute(conn,
        "DELETE FROM courses WHERE id = ? AND institution_id = ?",
        (course_id, institution_id)
    )
    conn.commit()
    conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_id(user_id):
    conn = get_conn()
    c = _execute(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    row = _fetchone(c)
    conn.close()
    return row


def get_user_by_username(username):
    conn = get_conn()
    c = _execute(conn, "SELECT * FROM users WHERE username = ?", (username,))
    row = _fetchone(c)
    conn.close()
    return row


def insert_user(username, password_hash, security_question,
                security_answer_hash, role, institution_id):
    conn = get_conn()
    if USE_PG:
        c = conn.cursor()
        c.execute("""
            INSERT INTO users
                (username, password_hash, security_question,
                 security_answer_hash, role, institution_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (username, password_hash, security_question,
              security_answer_hash, role, institution_id,
              datetime.utcnow().isoformat()))
        user_id = c.fetchone()[0]
    else:
        c = _execute(conn, """
            INSERT INTO users
                (username, password_hash, security_question,
                 security_answer_hash, role, institution_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, password_hash, security_question,
              security_answer_hash, role, institution_id,
              datetime.utcnow().isoformat()))
        user_id = c.lastrowid
    conn.commit()
    conn.close()
    return user_id


def count_users_in_institution(institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT COUNT(*) FROM users WHERE institution_id = ?", (institution_id,)
    )
    n = c.fetchone()[0]
    conn.close()
    return n


def get_all_users(institution_id=None):
    conn = get_conn()
    if institution_id:
        c = _execute(conn, """
            SELECT u.id, u.username, u.role, u.created_at, i.name as institution_name
            FROM users u LEFT JOIN institutions i ON u.institution_id = i.id
            WHERE u.institution_id = ?
            ORDER BY u.created_at
        """, (institution_id,))
    else:
        c = _execute(conn, """
            SELECT u.id, u.username, u.role, u.created_at, i.name as institution_name
            FROM users u LEFT JOIN institutions i ON u.institution_id = i.id
            ORDER BY i.name, u.created_at
        """)
    rows = _fetchall(c)
    conn.close()
    return rows


def update_user_role(user_id, role):
    conn = get_conn()
    _execute(conn, "UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    conn.commit()
    conn.close()


def update_user_password(username, password_hash):
    conn = get_conn()
    _execute(conn,
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (password_hash, username)
    )
    conn.commit()
    conn.close()


def count_admins_in_institution(institution_id):
    conn = get_conn()
    c = _execute(conn,
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND institution_id = ?",
        (institution_id,)
    )
    n = c.fetchone()[0]
    conn.close()
    return n


# ── Temp profiles ─────────────────────────────────────────────────────────────

def save_temp_profile(sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau):
    conn = get_conn()
    if USE_PG:
        conn.cursor().execute("""
            INSERT INTO temp_profiles
                (sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (sub_id) DO UPDATE SET
                psi_cell=EXCLUDED.psi_cell, psi_hidden=EXCLUDED.psi_hidden,
                psi_forget=EXCLUDED.psi_forget, window_w=EXCLUDED.window_w,
                window_w_tau=EXCLUDED.window_w_tau
        """, (sub_id, psi_cell, json.dumps(psi_hidden),
              psi_forget, json.dumps(window_w), json.dumps(window_w_tau),
              datetime.utcnow().isoformat()))
    else:
        _execute(conn, """
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
    c = _execute(conn, "SELECT * FROM temp_profiles WHERE sub_id = ?", (sub_id,))
    row = _fetchone(c)
    conn.close()
    if row is None:
        return None
    row["psi_hidden"]   = json.loads(row["psi_hidden"])
    row["window_w"]     = json.loads(row["window_w"])
    row["window_w_tau"] = json.loads(row["window_w_tau"])
    return row


def delete_temp_profile(sub_id):
    conn = get_conn()
    _execute(conn, "DELETE FROM temp_profiles WHERE sub_id = ?", (sub_id,))
    conn.commit()
    conn.close()
