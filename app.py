"""
app.py — AuthenticAI Flask application (multi-tenant).
"""

import os, io
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

import db, pipeline, batch_init, lecturer_batch
from auth import (
    init_users_table, get_user_by_id, verify_login, register_user,
    reset_password, get_security_question, SECURITY_QUESTIONS,
    get_all_users, promote_user, demote_user
)
from profile_diff import compute_diff

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "authenticai-dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

ALLOWED_EXTENSIONS = {"txt", "docx"}

# ── Flask-Login ───────────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to access AuthenticAI."
login_manager.login_message_category = "warning"

@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(int(user_id))


# ── Context processors ────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    flag_count = 0
    institution_name = ""
    try:
        if current_user.is_authenticated:
            inst_id = current_user.institution_id
            flags = db.get_pending_flags(institution_id=inst_id if not current_user.is_superadmin else None)
            flag_count = len(flags)
            if inst_id:
                inst = db.get_institution_by_id(inst_id)
                institution_name = inst["name"] if inst else ""
    except Exception:
        pass
    return {
        "pending_flag_count": flag_count,
        "current_user": current_user,
        "institution_name": institution_name,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────
def allowed_file(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def read_uploaded_file(file):
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    if ext == "txt":
        return file.read().decode("utf-8", errors="replace")
    elif ext == "docx":
        try:
            from docx import Document
            doc = Document(io.BytesIO(file.read()))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return None
    return None


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error, username = None, ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = verify_login(username, request.form.get("password", ""))
        if user:
            login_user(user)
            return redirect(request.args.get("next") or url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error, username=username)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    fields = {}
    if request.method == "POST":
        fields = {k: request.form.get(k, "") for k in
                  ["username","security_question","institution_name","institution_code"]}
        password   = request.form.get("password", "")
        confirm    = request.form.get("confirm_password", "")
        sec_ans    = request.form.get("security_answer", "")
        admin_code = request.form.get("admin_code", "")

        if password != confirm:
            error = "Passwords do not match."
        else:
            ok, result = register_user(
                fields["username"], password,
                fields["security_question"], sec_ans,
                fields["institution_name"], fields["institution_code"],
                admin_code
            )
            if ok:
                login_user(result)
                inst = db.get_institution_by_id(result.institution_id) if result.institution_id else None
                inst_name = inst["name"] if inst else "—"
                flash(f"Welcome, {result.username}! Joined {inst_name} as {result.role}.", "success")
                return redirect(url_for("index"))
            else:
                error = result

    return render_template("register.html",
        error=error, fields=fields,
        security_questions=SECURITY_QUESTIONS,
    )


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html", step=1)
    step     = int(request.form.get("step", 1))
    username = request.form.get("username", "").strip()
    if step == 1:
        question = get_security_question(username)
        if not question:
            return render_template("forgot_password.html", step=1,
                error="Username not found.", username=username)
        return render_template("forgot_password.html", step=2,
            username=username, security_question=question)
    elif step == 2:
        new_pw  = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        question = get_security_question(username)
        if new_pw != confirm:
            return render_template("forgot_password.html", step=2,
                username=username, security_question=question,
                error="Passwords do not match.")
        ok, err = reset_password(username, request.form.get("security_answer",""), new_pw)
        if ok:
            flash("Password reset successfully. Please sign in.", "success")
            return redirect(url_for("login"))
        return render_template("forgot_password.html", step=2,
            username=username, security_question=question, error=err)
    return redirect(url_for("forgot_password"))


# ── Main routes ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    inst_id  = current_user.institution_id
    students = db.get_students(inst_id)
    selected = request.args.get("student", students[0]["id"] if students else None)
    courses = db.get_courses(inst_id)
    submission_counts = {s["id"]: db.count_submissions(s["id"], inst_id) for s in students}
    return render_template("index.html",
        students=students, selected_id=selected,
        history=db.get_submissions_for_student(selected, inst_id) if selected else [],
        pending_flags=db.get_pending_flags(institution_id=inst_id),
        profile=db.get_profile(selected, inst_id) if selected else None,
        courses=courses,
        submission_counts=submission_counts,
    )


@app.route("/submit", methods=["POST"])
@login_required
def submit():
    inst_id         = current_user.institution_id
    student_id      = request.form.get("student_id")
    course_code = request.form.get("course_code", "Essay")
    text            = request.form.get("text", "").strip()
    uploaded        = request.files.get("file")
    if uploaded and uploaded.filename and allowed_file(uploaded.filename):
        ft = read_uploaded_file(uploaded)
        if ft:
            text = ft
        else:
            flash("Could not read uploaded file.", "error")
            return redirect(url_for("index", student=student_id))
    if len(text) < 50:
        flash("Submission text too short (minimum 50 characters).", "error")
        return redirect(url_for("index", student=student_id))
    try:
        result = pipeline.process_submission(student_id, inst_id, course_code, text)
        return redirect(url_for("result", sub_id=result["sub_id"]))
    except Exception as e:
        flash(f"Processing error: {e}", "error")
        return redirect(url_for("index", student=student_id))


@app.route("/result/<int:sub_id>")
@login_required
def result(sub_id):
    inst_id = current_user.institution_id
    sub = db.get_submission(sub_id, institution_id=inst_id if not current_user.is_superadmin else None)
    if not sub:
        flash("Submission not found.", "error")
        return redirect(url_for("index"))
    students = {s["id"]: s["name"] for s in db.get_students(inst_id or sub["institution_id"])}
    diff = compute_diff(sub.get("profile_before"), sub.get("profile_after"))
    from scoring import THETA
    return render_template("result.html", sub=sub,
        student_name=students.get(sub["student_id"], sub["student_id"]),
        theta=THETA(), profile_diff=diff)


@app.route("/flags")
@login_required
def flags():
    inst_id = current_user.institution_id if not current_user.is_superadmin else None
    all_flags = db.get_pending_flags(institution_id=inst_id)
    inst_id_for_students = current_user.institution_id or 0
    students = {s["id"]: s["name"] for s in db.get_students(inst_id_for_students)}
    return render_template("flags.html", flags=all_flags, students=students)


@app.route("/verify/<int:sub_id>", methods=["POST"])
@login_required
def verify(sub_id):
    decision   = request.form.get("decision")
    student_id = request.form.get("student_id")
    inst_id    = current_user.institution_id
    if decision not in ("genuine", "violation"):
        flash("Invalid decision.", "error")
        return redirect(url_for("result", sub_id=sub_id))
    msg = pipeline.lecturer_verify(sub_id, decision, student_id, inst_id)
    flash(msg, "success" if decision == "genuine" else "warning")
    return redirect(url_for("result", sub_id=sub_id))


@app.route("/batch", methods=["GET", "POST"])
@login_required
def batch():
    if not current_user.is_admin:
        flash("Student registration is restricted to admins.", "error")
        return redirect(url_for("index"))
    result = None
    if request.method == "POST":
        f = request.files.get("csv_file")
        if not f or not f.filename:
            flash("No CSV file selected.", "error")
            return redirect(url_for("batch"))
        csv_bytes = f.read()
        result = batch_init.run_batch(csv_bytes, current_user.institution_id)
        if result.ok:
            flash(
                f"Done — {result.created} student(s) added, {result.updated} updated.",
                "success"
            )
        else:
            flash(f"{result.failed} row(s) failed — see details below.", "warning")
    return render_template("batch.html", result=result)


@app.route("/about")
@login_required
def about():
    from scoring import signal1_keys, signal2_keys, THETA
    s1_descs = {
        "function_word_ratio":      "how often closed-class words appear",
        "pronoun_distribution":     "first-person vs all pronouns",
        "sentence_length_variance": "consistency of sentence rhythm",
        "type_token_ratio":         "vocabulary richness",
        "punctuation_rhythm":       "comma density per sentence",
    }
    s2_descs = {
        "avg_sentence_length":      "mean words per sentence",
        "passive_voice_ratio":      "proportion of passive constructions",
        "transition_word_density":  "connective phrases per sentence",
        "flesch_reading_ease":      "estimated reading ease (0–100)",
    }
    return render_template("about.html",
        signal1_features=[{"name": k, "desc": s1_descs[k]} for k in signal1_keys()],
        signal2_features=[{"name": k, "desc": s2_descs[k]} for k in signal2_keys()],
        theta=THETA())


@app.route("/admin")
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    inst_id = current_user.institution_id if not current_user.is_superadmin else None
    users   = get_all_users(institution_id=inst_id)
    institutions = db.get_all_institutions() if current_user.is_superadmin else []
    courses  = db.get_courses(current_user.institution_id) if not current_user.is_superadmin else []
    students = db.get_students(current_user.institution_id) if not current_user.is_superadmin else []
    return render_template("admin.html",
        users=users, current_id=current_user.id,
        institutions=institutions,
        courses=courses,
        students=students,
        is_superadmin=current_user.is_superadmin)


@app.route("/admin/promote/<int:user_id>", methods=["POST"])
@login_required
def admin_promote(user_id):
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    promote_user(user_id)
    flash("User promoted to admin.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/demote/<int:user_id>", methods=["POST"])
@login_required
def admin_demote(user_id):
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    ok, err = demote_user(user_id, current_user.institution_id)
    flash("User demoted to lecturer." if ok else err,
          "success" if ok else "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/students/delete/<student_id>", methods=["POST"])
@login_required
def admin_delete_student(student_id):
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    db.delete_student(student_id, current_user.institution_id)
    flash(f"Student {student_id} and all their data removed.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/admin/courses/add", methods=["POST"])
@login_required
def admin_add_course():
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    if not code or not name:
        flash("Course code and name are required.", "error")
        return redirect(url_for("admin_panel"))
    ok, err = db.add_course(code, name, current_user.institution_id)
    flash(f"Course {code} added." if ok else err,
          "success" if ok else "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/courses/delete/<int:course_id>", methods=["POST"])
@login_required
def admin_delete_course(course_id):
    if not current_user.is_admin:
        flash("Admin access required.", "error")
        return redirect(url_for("index"))
    db.delete_course(course_id, current_user.institution_id)
    flash("Course deleted.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/submit/batch", methods=["GET", "POST"])
@login_required
def submit_batch():
    inst_id = current_user.institution_id
    courses = db.get_courses(inst_id)
    result  = None

    if request.method == "POST":
        course_code = request.form.get("course_code", "").strip()
        files       = request.files.getlist("files")

        if not course_code:
            flash("Please select a course.", "error")
            return redirect(url_for("submit_batch"))
        if not files or not files[0].filename:
            flash("No files selected.", "error")
            return redirect(url_for("submit_batch"))

        import tempfile, shutil
        tmpdir = tempfile.mkdtemp()
        try:
            for f in files:
                if f.filename:
                    f.save(os.path.join(tmpdir, os.path.basename(f.filename)))
            result = lecturer_batch.run_lecturer_batch(tmpdir, course_code, inst_id)
            if result.succeeded > 0:
                flash(
                    f"Batch complete — {result.succeeded} submission(s) processed, "
                    f"{result.failed} failed, {result.skipped} skipped.",
                    "success" if result.failed == 0 else "warning"
                )
            else:
                flash("No submissions were processed successfully.", "error")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return render_template("submit_batch.html",
        courses=courses, result=result)


@app.route("/api/submission/<int:sub_id>")
@login_required
def api_submission(sub_id):
    inst_id = current_user.institution_id if not current_user.is_superadmin else None
    return jsonify(db.get_submission(sub_id, institution_id=inst_id) or {})


# ── Boot ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=5000)
