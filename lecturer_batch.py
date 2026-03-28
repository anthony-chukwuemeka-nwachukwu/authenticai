"""
lecturer_batch.py — Batch submission processing for lecturers.

Filename convention: {student_id}_{anything}.txt/.docx
  e.g. s001_essay1.txt, s001_essay2.txt, s005_reflection_draft.docx

Course is selected from the managed list — not inferred from filename.

Processing:
  - Files grouped by student_id (prefix before first underscore)
  - Within each student, sorted alphabetically (s001_essay1 < s001_essay2 < s001_essay4)
  - Each file runs through the normal pipeline (cold start or full scoring)
  - Failed files are skipped with error logged — processing continues
  - Unregistered student IDs are skipped with a warning
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FileResult:
    filename:   str
    student_id: str
    status:     str            # ok | skipped | failed
    verdict:    Optional[str] = None
    alpha_q:    Optional[float] = None
    alpha_s:    Optional[float] = None
    sub_id:     Optional[int] = None
    error:      Optional[str] = None


@dataclass
class LecturerBatchResult:
    course_code: str
    total:       int = 0
    succeeded:   int = 0
    skipped:     int = 0
    failed:      int = 0
    results:     list = field(default_factory=list)


def _parse_filename(filename):
    """
    Returns (student_id, ext) for valid files, None otherwise.
    student_id = everything before the first underscore.
    """
    base, ext = os.path.splitext(filename)
    ext = ext.lstrip(".").lower()
    if ext not in ("txt", "docx"):
        return None
    if "_" not in base:
        return None
    student_id = base.split("_")[0].strip()
    return (student_id, ext) if student_id else None


def _read_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".txt":
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    elif ext == ".docx":
        try:
            from docx import Document
            doc = Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            raise ValueError(f"Could not read .docx: {e}")
    raise ValueError(f"Unsupported type: {ext}")


def run_lecturer_batch(folder_path, course_code, institution_id):
    """
    Process all valid files as submissions for the given course + institution.
    Returns a LecturerBatchResult.
    """
    import db, pipeline

    result = LecturerBatchResult(course_code=course_code)

    if not os.path.isdir(folder_path):
        result.failed = 1
        result.results.append(FileResult("—", "—", "failed",
            error=f"Folder not found: {folder_path}"))
        return result

    # Registered students in this institution
    registered = {s["id"] for s in db.get_students(institution_id)}

    # Group files by student, sorted alphabetically within each student
    # {student_id: [sorted list of filenames]}
    student_files = {}
    for fname in sorted(os.listdir(folder_path)):
        parsed = _parse_filename(fname)
        if parsed is None:
            continue
        student_id, _ = parsed
        student_files.setdefault(student_id, []).append(fname)

    # Process: iterate students in sorted order, files in sorted order within each
    for student_id in sorted(student_files.keys()):
        files = student_files[student_id]  # already sorted

        # Check student is registered
        if student_id not in registered:
            for fname in files:
                result.total += 1
                result.skipped += 1
                result.results.append(FileResult(
                    filename=fname, student_id=student_id, status="skipped",
                    error=f"Student '{student_id}' not registered in this institution"
                ))
            continue

        # Process each file in order
        for fname in files:
            result.total += 1
            filepath = os.path.join(folder_path, fname)
            fr = FileResult(filename=fname, student_id=student_id, status="ok")

            try:
                text = _read_file(filepath)
                if len(text) < 50:
                    raise ValueError(f"Text too short ({len(text)} chars — minimum 50)")

                sub_result = pipeline.process_submission(
                    student_id, institution_id, course_code, text
                )
                fr.verdict  = sub_result["verdict"]
                fr.alpha_q  = sub_result["alpha_q"]
                fr.alpha_s  = sub_result["alpha_s"]
                fr.sub_id   = sub_result["sub_id"]
                result.succeeded += 1

            except Exception as e:
                fr.status = "failed"
                fr.error  = str(e)
                result.failed += 1

            result.results.append(fr)

    return result
