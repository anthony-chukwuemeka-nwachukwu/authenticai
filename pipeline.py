"""
pipeline.py — AuthenticAI submission processing pipeline (multi-tenant).

All operations are scoped by institution_id.
"""

import json
from scoring import (
    compute_alpha_q, compute_alpha_s,
    get_verdict, should_flag,
    update_window,
    signal1_keys, signal2_keys
)
from llm_calls import (
    call_1_extract_features,
    call_2a_update_profile, call_2b_explain, call_cold_start
)
import db


def process_submission(student_id, institution_id, course_code, text):
    """Algorithm 1 — scoped by institution_id."""
    n     = db.count_submissions(student_id, institution_id) + 1
    n_tau = db.count_submissions_by_type(student_id, institution_id, course_code)

    profile      = db.get_profile(student_id, institution_id)
    window_w     = profile["window_w"]     if profile else {}
    window_w_tau = profile["window_w_tau"] if profile else {}
    psi_cell     = profile.get("psi_cell")    if profile else None
    psi_hidden   = profile.get("psi_hidden", {}) if profile else {}
    psi_forget   = profile.get("psi_forget")  if profile else None

    if n <= 2:
        return _cold_start(
            student_id, institution_id, course_code, text, n,
            psi_cell, psi_hidden, psi_forget, window_w, window_w_tau
        )

    # ── Full pipeline ─────────────────────────────────────────────────────────
    features = call_1_extract_features(text)
    alpha_q  = compute_alpha_q(features, window_w)
    # Extract course-specific W_tau for Signal 2 scoring
    course_window_w_tau = window_w_tau.get(course_code, {})
    alpha_s  = compute_alpha_s(features, course_window_w_tau, n_tau)

    new_psi_cell, new_psi_hidden, new_psi_forget, psi_changes = \
        call_2a_update_profile(text, course_code, psi_cell, psi_hidden, psi_forget)

    new_window_w     = dict(window_w)
    new_window_w_tau = dict(window_w_tau)
    for k in signal1_keys():
        new_window_w = update_window(new_window_w, k, features[k])
    # W_tau is scoped by course_code: {course_code: {feature: [values]}}
    course_window = new_window_w_tau.get(course_code, {})
    for k in signal2_keys():
        course_window = update_window(course_window, k, features[k])
    new_window_w_tau[course_code] = course_window

    verdict, s1_state, s2_state = get_verdict(alpha_q, alpha_s)
    flagged = should_flag(alpha_q, alpha_s)

    explanation = None
    if flagged:
        explanation = call_2b_explain(
            text, course_code, psi_cell, psi_hidden,
            alpha_q, alpha_s, verdict
        )

    status = "flagged" if flagged else "clean"

    profile_before = {"psi_cell": psi_cell, "psi_hidden": psi_hidden, "psi_forget": psi_forget}
    profile_after  = {
        "psi_cell": new_psi_cell, "psi_hidden": new_psi_hidden,
        "psi_forget": new_psi_forget, "psi_changes": psi_changes
    }

    sub_id = db.save_submission(
        student_id, institution_id, course_code, text, features,
        alpha_q, alpha_s, verdict, explanation, status,
        profile_before=profile_before, profile_after=profile_after,
    )

    if not flagged:
        db.save_profile(student_id, institution_id,
            new_psi_cell, new_psi_hidden, new_psi_forget,
            new_window_w, new_window_w_tau)
    else:
        _store_temp_profile(sub_id, new_psi_cell, new_psi_hidden,
                            new_psi_forget, new_window_w, new_window_w_tau)

    return {
        "sub_id": sub_id, "submission_number": n,
        "features": features,
        "alpha_q": round(alpha_q, 4), "alpha_s": round(alpha_s, 4),
        "alpha_s_suppressed": n_tau < 3,
        "verdict": verdict, "signal1_state": s1_state, "signal2_state": s2_state,
        "flagged": flagged, "explanation": explanation, "status": status,
    }


def _cold_start(student_id, institution_id, course_code, text, n,
                psi_cell, psi_hidden, psi_forget, window_w, window_w_tau):
    new_psi_cell, new_psi_hidden, new_psi_forget = call_cold_start(text, course_code, n)
    psi_changes = {"added": ["Initial profile established."], "removed": [], "retained": []}

    features         = call_1_extract_features(text)
    new_window_w     = dict(window_w)
    new_window_w_tau = dict(window_w_tau)
    for k in signal1_keys():
        new_window_w = update_window(new_window_w, k, features[k])
    # W_tau is scoped by course_code: {course_code: {feature: [values]}}
    course_window = new_window_w_tau.get(course_code, {})
    for k in signal2_keys():
        course_window = update_window(course_window, k, features[k])
    new_window_w_tau[course_code] = course_window

    db.save_profile(student_id, institution_id,
        new_psi_cell, new_psi_hidden, new_psi_forget,
        new_window_w, new_window_w_tau)

    message = ("Baseline established — writing profile created."
               if n == 1 else "Profile building — submission recorded.")

    profile_snap = {
        "psi_cell": new_psi_cell, "psi_hidden": new_psi_hidden,
        "psi_forget": new_psi_forget, "psi_changes": psi_changes
    }

    sub_id = db.save_submission(
        student_id, institution_id, course_code, text, features,
        0.0, 0.0, "Baseline", message, "baseline",
        profile_before=None, profile_after=profile_snap,
    )

    return {
        "sub_id": sub_id, "submission_number": n, "features": features,
        "alpha_q": 0.0, "alpha_s": 0.0, "alpha_s_suppressed": True,
        "verdict": "Baseline", "signal1_state": "—", "signal2_state": "—",
        "flagged": False, "explanation": None, "status": "baseline", "message": message,
    }


# ── Lecturer Verify (Algorithm 2) ─────────────────────────────────────────────

def lecturer_verify(sub_id, decision, student_id, institution_id):
    if decision == "genuine":
        temp = _load_temp_profile(sub_id)
        if temp:
            db.save_profile(
                student_id, institution_id,
                temp["psi_cell"], temp["psi_hidden"], temp["psi_forget"],
                temp["window_w"], temp["window_w_tau"]
            )
            _delete_temp_profile(sub_id)
        db.update_submission_status(sub_id, "genuine")
        return "Profile updated — submission accepted as genuine."
    else:
        _delete_temp_profile(sub_id)
        db.update_submission_status(sub_id, "violation")
        return "Profile unchanged — violation recorded."


# ── Temp profile store ────────────────────────────────────────────────────────

def _store_temp_profile(sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau):
    db.save_temp_profile(sub_id, psi_cell, psi_hidden, psi_forget, window_w, window_w_tau)

def _load_temp_profile(sub_id):
    return db.load_temp_profile(sub_id)

def _delete_temp_profile(sub_id):
    db.delete_temp_profile(sub_id)
