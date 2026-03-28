"""
batch_init.py — Student registration from CSV for AuthenticAI.

Admin uploads a CSV file with columns: student_id, name
  e.g.
    s001,Alice Mensah
    s002,James Okoye

Students are created (or updated) in the institution. No text processing,
no LLM calls, no baseline initialization — that happens naturally when
lecturers submit student work through the normal submission flow.

Returns a BatchResult dataclass with per-student outcomes.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Optional
import db


@dataclass
class StudentResult:
    student_id:  str
    name:        str
    status:      str = "pending"   # ok | failed | updated
    error:       Optional[str] = None


@dataclass
class BatchResult:
    total:     int = 0
    created:   int = 0
    updated:   int = 0
    failed:    int = 0
    results:   list = field(default_factory=list)

    @property
    def ok(self):
        return self.failed == 0


def run_batch(csv_bytes, institution_id):
    """
    Parse a CSV file (bytes) and register students into the institution.
    Accepts:
      - Two columns: student_id, name
      - No header row required (header is detected and skipped automatically)

    Returns a BatchResult.
    """
    result = BatchResult()

    try:
        text = csv_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
    except Exception as e:
        sr = StudentResult("—", "—", status="failed", error=f"Could not parse CSV: {e}")
        result.failed = 1
        result.results.append(sr)
        return result

    existing = {s["id"] for s in db.get_students(institution_id)}

    for row in rows:
        # Skip blank lines
        if not row or all(cell.strip() == "" for cell in row):
            continue

        # Skip header row if present
        if row[0].strip().lower() in ("student_id", "id", "studentid"):
            continue

        if len(row) < 2:
            sr = StudentResult(
                row[0].strip() if row else "?", "?",
                status="failed",
                error="Row must have at least 2 columns: student_id, name"
            )
            result.failed += 1
            result.results.append(sr)
            continue

        student_id = row[0].strip()
        name       = row[1].strip()

        if not student_id:
            continue
        if not name:
            name = student_id

        result.total += 1
        was_existing = student_id in existing

        try:
            db.ensure_student(student_id, institution_id, name)
            sr = StudentResult(
                student_id, name,
                status="updated" if was_existing else "ok"
            )
            if was_existing:
                result.updated += 1
            else:
                result.created += 1
        except Exception as e:
            sr = StudentResult(student_id, name, status="failed", error=str(e))
            result.failed += 1

        result.results.append(sr)

    return result
