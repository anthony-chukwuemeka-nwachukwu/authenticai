"""
profile_diff.py — Compute human-readable diff between two writing profiles.

Primary source: psi_changes returned by Call 2A (LLM-articulated semantic diff).
Fallback: structural comparison for psi_hidden (field-by-field), sentence diff for psi_cell.

psi_hidden schema (per course):
  sentence_length, sentence_variability, vocabulary_complexity,
  tone, formality, function_word_patterns, structure, style_summary
"""

import re

_HIDDEN_FIELDS = [
    "sentence_length", "sentence_variability", "vocabulary_complexity",
    "tone", "formality", "function_word_patterns", "structure", "style_summary"
]


def _split_sentences(text):
    if not text:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _sentence_diff(before_text, after_text):
    before = _split_sentences(before_text)
    after  = _split_sentences(after_text)
    b_set  = set(before)
    a_set  = set(after)
    result = []
    for s in before:
        if s not in a_set:
            result.append({"text": s, "state": "removed"})
    for s in after:
        result.append({"text": s, "state": "unchanged" if s in b_set else "added"})
    return result


def _hidden_diff(before_hidden, after_hidden):
    """
    Compare psi_hidden dicts. Each value is either a structured dict (new schema)
    or a plain string (legacy). Returns per-type, per-field diffs.
    """
    before_hidden = before_hidden or {}
    after_hidden  = after_hidden  or {}
    all_types = sorted(set(list(before_hidden.keys()) + list(after_hidden.keys())))
    result = []

    for atype in all_types:
        b = before_hidden.get(atype)
        a = after_hidden.get(atype)

        # Normalise to dict
        def _to_dict(v):
            if v is None:
                return {}
            if isinstance(v, dict):
                return v
            return {"style_summary": str(v)}

        b_dict = _to_dict(b)
        a_dict = _to_dict(a)

        if not b_dict:
            # New course
            result.append({
                "atype": atype,
                "state": "added",
                "fields": [{"field": f, "before": None, "after": a_dict.get(f), "state": "added"}
                           for f in _HIDDEN_FIELDS if a_dict.get(f)]
            })
        elif not a_dict:
            result.append({
                "atype": atype,
                "state": "removed",
                "fields": []
            })
        else:
            fields = []
            any_changed = False
            for f in _HIDDEN_FIELDS:
                bv = b_dict.get(f)
                av = a_dict.get(f)
                if bv == av:
                    state = "unchanged"
                elif bv is None:
                    state = "added"
                    any_changed = True
                elif av is None:
                    state = "removed"
                    any_changed = True
                else:
                    state = "changed"
                    any_changed = True
                if bv or av:
                    fields.append({"field": f, "before": bv, "after": av, "state": state})
            result.append({
                "atype": atype,
                "state": "changed" if any_changed else "unchanged",
                "fields": fields
            })

    return result


def compute_diff(profile_before, profile_after):
    if not profile_before and not profile_after:
        return _empty()

    pb = profile_before or {}
    pa = profile_after  or {}

    # Hidden state: always structural field-by-field
    hidden_diff = _hidden_diff(pb.get("psi_hidden", {}), pa.get("psi_hidden", {}))

    # Primary: LLM-articulated psi_changes
    psi_changes  = pa.get("psi_changes") or {}
    llm_added    = psi_changes.get("added",    [])
    llm_removed  = psi_changes.get("removed",  [])
    llm_retained = psi_changes.get("retained", [])

    if llm_added or llm_removed or llm_retained:
        has_changes = bool(
            llm_added or llm_removed or
            any(d["state"] not in ("unchanged",) for d in hidden_diff)
        )
        return {
            "source":       "llm",
            "llm_added":    llm_added,
            "llm_removed":  llm_removed,
            "llm_retained": llm_retained,
            "cell":         [],
            "forget":       [],
            "hidden":       hidden_diff,
            "has_changes":  has_changes,
        }

    # Fallback: sentence-level string diff
    cell_diff   = _sentence_diff(pb.get("psi_cell",   ""), pa.get("psi_cell",   ""))
    forget_diff = _sentence_diff(pb.get("psi_forget", ""), pa.get("psi_forget", ""))
    has_changes = (
        any(d["state"] != "unchanged" for d in cell_diff)   or
        any(d["state"] != "unchanged" for d in forget_diff) or
        any(d["state"] not in ("unchanged",) for d in hidden_diff)
    )
    return {
        "source":       "string",
        "llm_added":    [],
        "llm_removed":  [],
        "llm_retained": [],
        "cell":         cell_diff,
        "forget":       forget_diff,
        "hidden":       hidden_diff,
        "has_changes":  has_changes,
    }


def _empty():
    return {
        "source": "string", "llm_added": [], "llm_removed": [],
        "llm_retained": [], "cell": [], "forget": [], "hidden": [],
        "has_changes": False,
    }
