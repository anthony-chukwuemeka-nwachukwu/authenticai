"""
auth.py — Authentication for AuthenticAI (multi-tenant).

Institution logic:
  - Institution code provided at registration
  - If code exists  → join that institution
  - If code is new  → create institution, first user becomes its admin
  - ADMIN_CODE env  → grants admin role within the institution

Roles:
  superadmin — cross-institution, set via SUPERADMIN_CODE env var
  admin      — institution-scoped admin
  lecturer   — institution-scoped
"""

import os
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import db

SECURITY_QUESTIONS = [
    "What was your first pet's name?",
    "What city were you born in?",
    "What is your mother's maiden name?",
    "What was the name of your first school?",
]


# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username, role, institution_id):
        self.id             = id
        self.username       = username
        self.role           = role
        self.institution_id = institution_id

    @property
    def is_admin(self):
        return self.role in ("admin", "superadmin")

    @property
    def is_superadmin(self):
        return self.role == "superadmin"


# ── DB helpers ────────────────────────────────────────────────────────────────

def init_users_table():
    """Users table is part of init_db — this is a no-op kept for compatibility."""
    pass


def get_user_by_id(user_id):
    row = db.get_user_by_id(user_id)
    if row:
        return User(row["id"], row["username"], row["role"], row["institution_id"])
    return None


def get_user_by_username(username):
    return db.get_user_by_username(username)


def get_all_users(institution_id=None):
    conn = db.get_conn()
    if institution_id:
        rows = conn.execute("""
            SELECT u.id, u.username, u.role, u.created_at, i.name as institution_name
            FROM users u LEFT JOIN institutions i ON u.institution_id = i.id
            WHERE u.institution_id = ?
            ORDER BY u.created_at
        """, (institution_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT u.id, u.username, u.role, u.created_at, i.name as institution_name
            FROM users u LEFT JOIN institutions i ON u.institution_id = i.id
            ORDER BY i.name, u.created_at
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_users_in_institution(institution_id):
    return db.count_users_in_institution(institution_id)


# ── Registration ──────────────────────────────────────────────────────────────

def register_user(username, password, security_question, security_answer,
                  institution_name, institution_code, admin_code=""):
    """
    Register a new user.
    - If institution_code exists → join it
    - If institution_code is new → create institution, user becomes admin
    - ADMIN_CODE env match → admin role within institution
    - SUPERADMIN_CODE env match → superadmin role (no institution scope)
    Returns (True, user_obj) or (False, error_message).
    """
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters."
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters."
    if security_question not in SECURITY_QUESTIONS:
        return False, "Invalid security question."
    if not security_answer or len(security_answer.strip()) < 2:
        return False, "Security answer is required."
    if not institution_code or len(institution_code.strip()) < 3:
        return False, "Institution code must be at least 3 characters."

    institution_code = institution_code.strip().upper()
    admin_code_env      = os.environ.get("ADMIN_CODE", "")
    superadmin_code_env = os.environ.get("SUPERADMIN_CODE", "")

    # Superadmin path — no institution needed
    if superadmin_code_env and admin_code.strip() == superadmin_code_env:
        institution_id = None
        role = "superadmin"
    else:
        # Resolve institution
        institution = db.get_institution_by_code(institution_code)
        if institution:
            institution_id = institution["id"]
            # Determine role within this institution
            code_matches = admin_code_env and admin_code.strip() == admin_code_env
            role = "admin" if code_matches else "lecturer"
        else:
            # Create new institution — first user becomes its admin
            if not institution_name or len(institution_name.strip()) < 2:
                return False, "Institution name is required when creating a new institution."
            institution_id = db.create_institution(
                institution_name.strip(), institution_code
            )
            if not institution_id:
                return False, "Institution code already taken."
            role = "admin"

    try:
        user_id = db.insert_user(
            username.strip(),
            generate_password_hash(password),
            security_question,
            generate_password_hash(security_answer.strip().lower()),
            role,
            institution_id
        )
        return True, User(user_id, username.strip(), role, institution_id)
    except Exception:
        return False, "Username already taken."


# ── Login ─────────────────────────────────────────────────────────────────────

def verify_login(username, password):
    row = get_user_by_username(username)
    if row and check_password_hash(row["password_hash"], password):
        return User(row["id"], row["username"], row["role"], row["institution_id"])
    return None


# ── Password reset ────────────────────────────────────────────────────────────

def get_security_question(username):
    row = get_user_by_username(username)
    return row["security_question"] if row else None


def reset_password(username, security_answer, new_password):
    if not new_password or len(new_password) < 6:
        return False, "New password must be at least 6 characters."
    row = get_user_by_username(username)
    if not row:
        return False, "Username not found."
    if not check_password_hash(row["security_answer_hash"], security_answer.strip().lower()):
        return False, "Security answer is incorrect."
    db.update_user_password(username, generate_password_hash(new_password))
    return True, None


# ── Role management ───────────────────────────────────────────────────────────

def promote_user(user_id):
    db.update_user_role(user_id, 'admin')
    return True, None


def demote_user(user_id, institution_id):
    if db.count_admins_in_institution(institution_id) <= 1:
        return False, "Cannot demote the last admin of this institution."
    db.update_user_role(user_id, 'lecturer')
    return True, None
