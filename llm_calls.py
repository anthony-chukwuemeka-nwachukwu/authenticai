"""
llm_calls.py — The three AuthenticAI LLM calls.

All provider logic lives in llm_client.py. This module only defines
prompts and parses responses.

Call 1  — Feature Extractor  (always fires, stateless, returns 9 floats)
Call 2A — Profile Updater    (always fires, reads P_perm, writes P_temp)
Call 2B — Anomaly Explainer  (fires only when |αQ| ≥ θ or αS ≥ θ)
"""

import json
from llm_client import chat


def _parse_json(raw: str, fallback: dict) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return fallback


# ── Shared style rules injected into every prompt ────────────────────────────

_STYLE_RULES = """You are a stylometric analysis system. Your task is to analyse writing STYLE ONLY, not content.

STRICT RULES:
- Do NOT summarise the text
- Do NOT interpret the topic
- Do NOT evaluate correctness or meaning
- Ignore subject matter entirely
- Focus only on HOW the text is written"""


# ── Call 1: Feature Extractor ────────────────────────────────────────────────

CALL_1_SYSTEM = _STYLE_RULES + """

Extract exactly 9 numerical stylometric features.
Return ONLY a valid JSON object with these 9 keys and float values.
No explanation, no preamble, no markdown fences. Just raw JSON.

Signal 1 — Assignment-invariant (stable regardless of topic or genre):
  "function_word_ratio"       : proportion of closed-class words (the, and, however,
                                 by, of, because, although...) out of all words. ~0.3–0.6
  "pronoun_distribution"      : ratio of first-person pronouns (I, me, my, we, our)
                                 to all pronouns used. Range 0.0–1.0
  "sentence_length_variance"  : standard deviation of sentence lengths in words.
                                 Captures rhythmic consistency. Typically 2–20.
  "type_token_ratio"          : root TTR (unique words / sqrt(total words)).
                                 Vocabulary richness independent of topic. Typically 5–15.
  "punctuation_rhythm"        : average commas per sentence. Reflects syntactic
                                 complexity and thought structure. Typically 0.3–3.0.

Signal 2 — Assignment-aware (vary by genre convention, not topic):
  "avg_sentence_length"       : mean words per sentence. Typically 10–35.
  "passive_voice_ratio"       : proportion of sentences using passive constructions.
                                 Assess structurally. Range 0.0–0.8.
  "transition_word_density"   : average connective phrases per sentence
                                 (however, therefore, furthermore, as a result...).
                                 Reflects genre conventions. Typically 0.0–1.5.
  "flesch_reading_ease"       : estimated Flesch Reading Ease (0–100).
                                 Academic writing typically 30–60."""

_FEATURE_KEYS = [
    "function_word_ratio", "pronoun_distribution", "sentence_length_variance",
    "type_token_ratio", "punctuation_rhythm",
    "avg_sentence_length", "passive_voice_ratio",
    "transition_word_density", "flesch_reading_ease",
]

_FEATURE_FALLBACK = {
    "function_word_ratio": 0.45, "pronoun_distribution": 0.5,
    "sentence_length_variance": 5.0, "type_token_ratio": 8.0,
    "punctuation_rhythm": 0.8, "avg_sentence_length": 18.0,
    "passive_voice_ratio": 0.1, "transition_word_density": 0.3,
    "flesch_reading_ease": 50.0,
}


def call_1_extract_features(text: str) -> dict:
    """Call 1 — always fires. Stateless. Returns 9-feature dict."""
    user = f"Extract the 9 stylometric features from this text:\n\n\"\"\"\n{text[:4000]}\n\"\"\""
    raw = chat(CALL_1_SYSTEM, user, max_tokens=256)
    parsed = _parse_json(raw, _FEATURE_FALLBACK)
    result = {}
    for k in _FEATURE_KEYS:
        v = parsed.get(k, _FEATURE_FALLBACK[k])
        # Guard: LLM sometimes returns nested dicts — flatten to fallback
        if isinstance(v, (dict, list)):
            v = _FEATURE_FALLBACK[k]
        try:
            result[k] = round(float(v), 4)
        except (TypeError, ValueError):
            result[k] = _FEATURE_FALLBACK[k]
    return result


# ── Call 2A: Profile Updater ─────────────────────────────────────────────────

CALL_2A_SYSTEM = _STYLE_RULES + """

You are maintaining a longitudinal writing identity profile (Ψ) for a student,
modelled on LSTM gate architecture. Every field must describe writing style only.

The profile has four components:

psi_cell (Cell State):
  Long-term stable writing identity — style traits observed consistently across
  multiple courses. Update slowly; only strengthen or add with recurring evidence.
  Describe using these dimensions where applicable:
    - Sentence structure: length tendency, variability, complexity
    - Vocabulary: richness, register (simple/moderate/advanced), hedging patterns
    - Tone: personal vs impersonal
    - Formality: formal vs informal
    - Function word patterns: e.g. heavy use of "I", "however", "but"
    - Structural tendencies: use of transitions, paragraph flow
    - Stylistic fingerprint: descriptive vs analytical, concise vs verbose, direct vs hedged

psi_hidden (Hidden State):
  Per-course recent style tendencies. Dict keyed by course code.
  Each value must be a JSON object with these fields (all strings):
    {
      "sentence_length":        "short / medium / long",
      "sentence_variability":   "low / medium / high",
      "vocabulary_complexity":  "simple / moderate / advanced",
      "tone":                   "personal / impersonal / mixed",
      "formality":              "formal / informal / mixed",
      "function_word_patterns": "brief description of notable patterns",
      "structure":              "linear / fragmented / layered",
      "style_summary":          "2-sentence style-only summary"
    }

psi_forget (Forget Candidates):
  Style traits once present but absent from recent submissions.

psi_changes (Change Summary):
  What changed in this update. Three keys:
    "added":    list of short strings — new style traits added
    "removed":  list of short strings — style traits removed or flagged for forget
    "retained": list of short strings — key stable style traits kept unchanged

Return ONLY valid JSON with keys: psi_cell, psi_hidden, psi_forget, psi_changes.
No preamble, no markdown fences. Just the JSON."""


def call_2a_update_profile(text, course_code, psi_cell, psi_hidden, psi_forget):
    """Call 2A — always fires. Reads P_perm. Returns updated (psi_cell, psi_hidden, psi_forget, psi_changes)."""
    current = {
        "psi_cell": psi_cell or "No profile yet — early submission.",
        "psi_hidden": psi_hidden or {},
        "psi_forget": psi_forget or "None identified yet.",
    }
    user = (
        f"Course code: {course_code}\n"
        f"Use '{course_code}' as the key in psi_hidden for this submission.\n\n"
        f"Current profile:\n{json.dumps(current, indent=2)}\n\n"
        f"New submission:\n\"\"\"\n{text[:3000]}\n\"\"\"\n\n"
        f"Update and return the profile JSON including psi_changes."
    )
    _default_changes = {"added": [], "removed": [], "retained": []}
    raw = chat(CALL_2A_SYSTEM, user, max_tokens=1024)
    updated = _parse_json(raw, {**current, "psi_changes": _default_changes})
    return (
        updated.get("psi_cell", psi_cell),
        updated.get("psi_hidden", psi_hidden or {}),
        updated.get("psi_forget", psi_forget),
        updated.get("psi_changes", _default_changes),
    )


# ── Call 2B: Anomaly Explainer ───────────────────────────────────────────────

CALL_2B_SYSTEM = _STYLE_RULES + """

A submission has triggered the anomaly detector because its stylometric scores
exceeded the detection threshold. Explain to a lecturer what is unusual about
this submission compared to the student's established writing profile.

Reference the specific style dimensions that shifted:
  - Sentence length and variability
  - Vocabulary complexity and register
  - Tone (personal → impersonal or vice versa)
  - Formality level
  - Function word patterns (e.g. first-person pronouns disappeared)
  - Structural patterns (transition density, paragraph flow)
  - Stylistic fingerprint (e.g. suddenly verbose, suddenly hedged)

Do NOT mention the topic or subject matter of the essay.
Do NOT say "written by AI" — report the stylometric anomaly only.
3–5 sentences. Direct and professional."""


def call_2b_explain(text, course_code, psi_cell, psi_hidden, alpha_q, alpha_s, verdict):
    """Call 2B — fires only when |αQ| ≥ θ or αS ≥ θ. Reads P_perm. Writes nothing."""
    profile = (
        f"Cell State (stable style identity):\n{psi_cell or 'Not yet established.'}\n\n"
        f"Hidden State (recent per-type style):\n{json.dumps(psi_hidden or {}, indent=2)}"
    )
    direction = "simplification (sudden drop)" if alpha_q < 0 else "sophistication spike"
    user = (
        f"Course: {course_code}\n"
        f"Verdict: {verdict}\n"
        f"Signal 1 (αQ): {alpha_q:.3f} — {direction} [threshold: ±2.5]\n"
        f"Signal 2 (αS): {alpha_s:.3f} [threshold: 2.5]\n\n"
        f"Student's established writing profile:\n{profile}\n\n"
        f"Flagged submission (first 2000 chars):\n\"\"\"\n{text[:2000]}\n\"\"\"\n\n"
        f"Explain the style anomaly to the lecturer."
    )
    result = chat(CALL_2B_SYSTEM, user, max_tokens=512)
    return result if isinstance(result, str) else str(result)


# ── Cold Start: seed profile ─────────────────────────────────────────────────

COLD_START_SYSTEM = _STYLE_RULES + """

A student is submitting for the first or second time. Generate a seed writing profile.

Return ONLY valid JSON with keys:
  psi_cell:   string describing apparent stable writing style traits using these dimensions:
              sentence structure, vocabulary, tone, formality, function word patterns,
              structural tendencies, stylistic fingerprint
  psi_hidden: dict with course_code as key, value is a JSON object with fields:
              sentence_length, sentence_variability, vocabulary_complexity, tone,
              formality, function_word_patterns, structure, style_summary
  psi_forget: empty string

No preamble, no markdown. Just the JSON."""


def call_cold_start(text, course_code, submission_number):
    user = (
        f"Submission number: {submission_number}\n"
        f"Course: {course_code}\n\n"
        f"Submission:\n\"\"\"\n{text[:3000]}\n\"\"\"\n\n"
        f"Generate the initial writing style profile."
    )
    fallback = {
        "psi_cell": "Writing style profile being established.",
        "psi_hidden": {course_code: {
            "sentence_length": "medium",
            "sentence_variability": "medium",
            "vocabulary_complexity": "moderate",
            "tone": "mixed",
            "formality": "mixed",
            "function_word_patterns": "standard usage",
            "structure": "linear",
            "style_summary": "Initial submission recorded. Profile building."
        }},
        "psi_forget": "",
    }
    raw = chat(COLD_START_SYSTEM, user, max_tokens=512)
    profile = _parse_json(raw, fallback)
    return (
        profile.get("psi_cell", fallback["psi_cell"]),
        profile.get("psi_hidden", fallback["psi_hidden"]),
        profile.get("psi_forget", ""),
    )
