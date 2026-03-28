# AuthenticAI — Modeling the Writer, Not the Text

> *Existing academic integrity tools ask: does this look like AI wrote it?*
> *AuthenticAI asks the right question: does this look like **this student** wrote it?*

**WashU AI Week 2026 · Built for Mastercard Innovation Challenge**

---

## The Problem

Academic integrity tools like Turnitin and GPTZero compare submissions against AI output distributions or external corpora. This approach has a fundamental flaw — it models the output of AI systems, not the identity of individual writers. As generative AI improves and better mimics human style, these tools become increasingly unreliable, and they disproportionately flag non-native English speakers.

The right signal has been available all along: **the student's own writing history.**

---

## What AuthenticAI Does

AuthenticAI builds a persistent, evolving writing identity profile for each student across all their submissions. When a new submission arrives, it is scored not against a population of AI-generated text, but against **that student's own longitudinal fingerprint**.

A flag fires when a submission deviates discontinuously from a student's established trajectory — distinguishing natural academic growth from sudden stylistic jumps consistent with AI generation or ghost-writing.

This mirrors how Mastercard's own fraud detection works: not "does this transaction look suspicious in general?" but "does this transaction look like **this cardholder**?"

---

## Architecture

AuthenticAI combines a quantitative scoring layer with a qualitative LLM-based identity layer, unified by a three-call pipeline and a two-tier baseline architecture.

### The Three LLM Calls

| Call | Fires | Role |
|---|---|---|
| **Call 1 — Feature Extractor** | Every submission | LLM semantically extracts a 9-feature stylometric vector. No brittle keyword heuristics. |
| **Call 2A — Profile Updater** | Every submission | LLM updates the student's writing identity profile Ψ using a prompted LSTM mechanism. Reads from Permanent Baseline, writes to Temporal Baseline. |
| **Call 2B — Anomaly Explainer** | When flagged only | LLM generates a plain-language explanation for the lecturer. Cost-proportional to anomaly frequency. |

### Two-Signal Scoring

**Signal 1 — αQ (Assignment-Invariant)**
Measures deviation from the student's overall writing identity across all submissions and courses. Function word ratio, pronoun distribution, sentence rhythm, vocabulary richness. A spike here is the most suspicious pattern — these features are the hardest to consciously fake.

**Signal 2 — αS (Course-Aware)**
Measures deviation from the student's typical style within a specific course. Compared only against prior submissions to the same course. Suppressed until sufficient same-course history exists.

Both signals are z-scores against the student's own sliding window baseline. Flagging fires when |αQ| ≥ θ or αS ≥ θ.

### Two-Tier Baseline Architecture

Submissions that flag are never automatically incorporated into the student's permanent profile. Instead:

- **P_perm** — Verified permanent baseline. Only updated on clean submissions or lecturer-confirmed genuine work.
- **P_temp** — Provisional update, held until the lecturer decides. On violation: rolled back. On genuine: promoted to P_perm.

This guarantees the permanent fingerprint can only advance via verified evidence.

### Prompted LSTM

The qualitative profile Ψ mimics LSTM gate architecture in natural language:
- **Cell state** — Long-term stable writing identity across all courses
- **Hidden state** — Recent per-course style tendencies
- **Forget candidates** — Traits no longer observed, flagged for removal

The LLM acts as the gating function. Context window cost is constant regardless of submission history length.

---

## Key Features

- **Multi-tenant** — Institution-scoped isolation. Multiple universities run simultaneously with no data crossing boundaries.
- **Provider-agnostic** — Anthropic, Azure OpenAI, or OpenAI direct. Switch by changing env vars only.
- **Lecturer verification loop** — Full Genuine / Violation decision flow with profile promotion and rollback.
- **Profile evolution diff** — LLM-articulated before/after view showing exactly which style dimensions shifted.
- **Course-scoped Signal 2** — W_τ window keyed per course. Lab reports compared only against prior lab reports.
- **Verified Baseline Acquisition Framework** — Supervised onboarding sessions seed P_perm before coursework begins.
- **Batch submission** — Lecturers upload a folder of student texts at once. Admin registers students via CSV.

---

## Verdict Table

| Signal 1 | Signal 2 | Verdict |
|---|---|---|
| Normal | Normal | ✅ Clean |
| Normal | Spike | 🟡 Monitor |
| Spike | Normal | 🟠 Investigate |
| Spike | Spike | 🔴 Strong Flag |
| Drop | Normal | 🟠 Simplification |

Signal 1 spiking alone is the most suspicious case — these features are the hardest to consciously manipulate.

---

## Tech Stack

- **Backend** — Python, Flask, SQLite (WAL mode)
- **LLM** — Anthropic Claude / Azure OpenAI / OpenAI (configurable)
- **Auth** — Flask-Login, Werkzeug password hashing
- **Frontend** — Vanilla HTML/CSS/JS, dark theme, no framework dependencies

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your API keys to .env
python app.py
# → http://localhost:5000
```

### Environment variables

```bash
# LLM provider (anthropic | azure | openai)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Detection threshold (default 2.5)
AUTHENTICAI_THETA=2.5

# Admin registration code
ADMIN_CODE=your-secret-code
```

See `.env.example` for full configuration including Azure OpenAI.

---

## First-time Workflow

1. **Register** → create institution with a unique code
2. **Admin panel** → add courses (e.g. `ESS101 — Essay Writing`)
3. **Students page** → upload CSV (`student_id, name`)
4. **Batch Submit** → upload baseline submissions per course
5. **Dashboard** → live submission scoring begins from submission 3+
6. **Flags** → review anomalies, mark Genuine or Violation

---

## Research

This system implements the architecture described in:

> Nwachukwu, A. (2026). *AuthenticAI: Modeling the Writer, Not the Text — A Longitudinal Identity Framework for Academic Integrity in the Age of Generative AI.* WashU AI Week 2026.

The paper covers the full formal specification including Algorithm 1 (submission processing), Algorithm 2 (LecturerVerify), the Verified Baseline Acquisition Framework, limitations, and future work directions.

---

## Author

**Anthony Nwachukwu**
PhD Candidate, Computer Science · MBA Candidate (Wealth & Asset Management)
Washington University in St. Louis, Olin Business School
