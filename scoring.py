import os
import math
from dotenv import load_dotenv
load_dotenv()


"""
scoring.py — Sliding window baseline, z-score computation, αQ, αS, verdict.

Implements the math from the paper:
  - W_n  : full-history sliding window storing cumulative means (Signal 1)
  - W_τ  : same-type sliding window (Signal 2)
  - z_j  : per-feature z-score, capped at ±MAX_Z to prevent overflow
  - αQ   : mean z-score over Signal 1 features  (ℝ, can be negative)
  - αS   : mean z-score over Signal 2 features  (ℝ≥0, suppressed if nτ < 3)
  - θ    : configurable via AUTHENTICAI_THETA env var (default 2.5)

Z-score overflow fix:
  σ collapses to ~0 when baseline submissions are nearly identical (common
  with only 2 points). Three-layer defence:
    1. MIN_SIGMA floor — σ is clamped to at least 5% of |μ| or MIN_SIGMA_ABS
    2. epsilon=0.01 — larger smoothing constant as secondary guard
    3. MAX_Z cap — z-scores are clamped to [-10, 10] before aggregation
"""

# ── Constants ─────────────────────────────────────────────────────────────────

def THETA():
    """Read threshold at call time so env var changes are respected."""
    return float(os.environ.get("AUTHENTICAI_THETA", "1.5"))

K         = 10     # sliding window size
MIN_TAU   = 2      # min same-type submissions before αS activates
MAX_Z     = 10.0   # z-score cap — prevents overflow from σ ≈ 0
EPSILON   = 0.005  # smoothing constant added to σ
MIN_SIGMA_REL = float(os.environ.get("AUTHENTICAI_SIGMA_REL", "0.02"))  # σ floor as fraction of |μ|
MIN_SIGMA_ABS = 0.001  # absolute σ floor when μ ≈ 0


# ── Feature key lists ─────────────────────────────────────────────────────────

def signal1_keys():
    """Signal 1 — assignment-invariant (compared across all submissions)."""
    return [
        "function_word_ratio",
        "pronoun_distribution",
        "sentence_length_variance",
        "type_token_ratio",
        "punctuation_rhythm",
    ]


def signal2_keys():
    """Signal 2 — assignment-aware (compared within same type only)."""
    return [
        "avg_sentence_length",
        "passive_voice_ratio",
        "transition_word_density",
        "flesch_reading_ease",
    ]


# ── Math helpers ──────────────────────────────────────────────────────────────

def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _std(values):
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _sigma_floor(sigma, mu):
    """
    Apply a minimum sigma to prevent z-score explosion when baseline
    submissions are nearly identical (σ → 0).
    Floor is max(MIN_SIGMA_REL * |μ|, MIN_SIGMA_ABS).
    """
    floor = max(MIN_SIGMA_REL * abs(mu), MIN_SIGMA_ABS)
    return max(sigma, floor)


def z_score(value, window_values):
    """
    Compute z-score of value against window, with overflow protection.
    Returns a value clamped to [-MAX_Z, MAX_Z].
    """
    if len(window_values) < 2:
        return 0.0
    mu    = _mean(window_values)
    sigma = _std(window_values)
    sigma = _sigma_floor(sigma, mu)   # prevent collapse
    z     = (value - mu) / (sigma + EPSILON)
    return max(-MAX_Z, min(MAX_Z, z)) # cap


# ── Window management ─────────────────────────────────────────────────────────

def update_window(window_dict, feature_key, new_value, k=K):
    """
    Append the new cumulative mean μ_n^(j) to the window.
    W_n = [μ_{n-k+1}, ..., μ_n] — stores cumulative means, not raw values.
    """
    history = window_dict.get(feature_key, [])
    n = len(history) + 1
    if history:
        new_mean = ((n - 1) * history[-1] + new_value) / n
    else:
        new_mean = new_value
    history.append(round(new_mean, 6))
    if len(history) > k:
        history = history[-k:]
    window_dict[feature_key] = history
    return window_dict


# ── Score computation ─────────────────────────────────────────────────────────

def compute_alpha_q(features, window_w):
    """
    αQ = mean z-score over Signal 1 invariant features. ∈ ℝ (can be negative).
    """
    keys = signal1_keys()
    if not any(window_w.get(k) for k in keys):
        return 0.0

    z_scores = []
    for k in keys:
        hist = window_w.get(k, [])
        if len(hist) >= 2:
            z_scores.append(z_score(features[k], hist))

    return _mean(z_scores) if z_scores else 0.0


def compute_alpha_s(features, window_w_tau, n_tau):
    """
    αS = mean z-score over Signal 2 features. ∈ ℝ≥0.
    Returns 0.0 if nτ < MIN_TAU (suppressed).
    """
    if n_tau < MIN_TAU:
        return 0.0

    keys = signal2_keys()
    z_scores = []
    for k in keys:
        hist = window_w_tau.get(k, [])
        if len(hist) >= 2:
            z_scores.append(z_score(features[k], hist))

    return max(0.0, _mean(z_scores)) if z_scores else 0.0


# ── Verdict ───────────────────────────────────────────────────────────────────

def get_verdict(alpha_q, alpha_s):
    """
    Verdict table using |αQ| for Signal 1 (both directions flagged).
    Negative αQ = simplification anomaly, positive = sophistication spike.
    """
    theta = THETA()
    s1_spike = alpha_q >= theta          # sudden sophistication increase
    s1_drop  = alpha_q <= -theta         # sudden simplification
    s1       = s1_spike or s1_drop
    s2       = alpha_s >= theta

    if s1_spike and s2:
        return "Strong Flag", "Spike", "Spike"
    elif s1_spike and not s2:
        return "Investigate", "Spike", "Normal"
    elif s1_drop and s2:
        return "Strong Flag", "Drop+Spike", "Spike"
    elif s1_drop and not s2:
        return "Simplification", "Drop", "Normal"
    elif not s1 and s2:
        return "Monitor", "Normal", "Spike"
    else:
        return "Clean", "Normal", "Normal"


def should_flag(alpha_q, alpha_s):
    """Flag on |αQ| ≥ θ (both directions) or αS ≥ θ (upward only)."""
    theta = THETA()
    return abs(alpha_q) >= theta or alpha_s >= theta