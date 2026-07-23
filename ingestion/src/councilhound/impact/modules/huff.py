"""Huff spatial-interaction math — pure numpy, no geo dependencies.

P_ij = A_j^alpha * exp(-beta * t_ij) / sum_k A_k^alpha * exp(-beta * t_ik)

Kept free of geodata so the hand-computed toy-case unit test runs in the
base CI environment, and so the math is auditable in one screenful.
"""
from __future__ import annotations

import numpy as np


def huff_probabilities(attractiveness: np.ndarray, times_min: np.ndarray,
                       alpha: float = 1.0, beta: float = 0.10) -> np.ndarray:
    """Destination-choice probabilities for one origin.

    attractiveness: A_j per destination (>= 0); times_min: t_ij in minutes.
    Destinations with zero attractiveness get zero probability. Unreachable
    destinations should be passed with t=inf (exp(-inf) -> 0)."""
    attractiveness = np.asarray(attractiveness, dtype=float)
    times_min = np.asarray(times_min, dtype=float)
    if attractiveness.shape != times_min.shape:
        raise ValueError("attractiveness and times must align")
    utility = np.power(attractiveness, alpha, where=attractiveness > 0,
                       out=np.zeros_like(attractiveness))
    with np.errstate(over="ignore"):
        utility = utility * np.exp(-beta * times_min)
    total = utility.sum()
    if total <= 0:
        return np.zeros_like(utility)
    return utility / total


def blended_probabilities(attractiveness: np.ndarray, walk_min: np.ndarray,
                          drive_min: np.ndarray, walk_share: float,
                          alpha: float = 1.0, beta_walk: float = 0.10,
                          beta_drive: float = 0.15) -> np.ndarray:
    """Mode-split blend: walk_share of trips choose by walk impedance, the
    rest by drive impedance. Each mode's probabilities sum to 1 (or 0 when
    nothing is reachable), so the blend preserves total spend."""
    p_walk = huff_probabilities(attractiveness, walk_min, alpha, beta_walk)
    p_drive = huff_probabilities(attractiveness, drive_min, alpha, beta_drive)
    if p_walk.sum() == 0:
        return p_drive
    if p_drive.sum() == 0:
        return p_walk
    return walk_share * p_walk + (1.0 - walk_share) * p_drive


def joint_multimode_probabilities(
        attractiveness: np.ndarray,
        modes: list[tuple[float, float, np.ndarray]],
        alpha: float = 1.0) -> tuple[np.ndarray, list[np.ndarray]]:
    """One choice over (destination, mode) pairs -> (p_total, [p_mode ...]).

    modes: (pref, beta, times_min) per mode, where pref is that mode's share
    when every mode costs nothing (prefs should sum to 1):

        utility_m = A^a * pref_m * exp(-beta_m * t_m)

    At t=0 across the board each mode's share equals its pref; a mode whose
    utility decays to nothing at a destination loses those trips to the
    others. So unlike the separate-normalization blend, per-mode dollars are
    NOT forced to sum to the mode-split budget — taking a slow mode somewhere
    implausible loses to the faster ones, which is what makes per-destination
    per-mode capture meaningful."""
    attractiveness = np.asarray(attractiveness, dtype=float)
    base = np.power(attractiveness, alpha, where=attractiveness > 0,
                    out=np.zeros_like(attractiveness))
    with np.errstate(over="ignore"):
        utils = [base * pref * np.exp(-beta * np.asarray(times, dtype=float))
                 for pref, beta, times in modes]
    total = sum(u.sum() for u in utils)
    if total <= 0:
        return np.zeros_like(base), [np.zeros_like(base) for _ in modes]
    return sum(utils) / total, [u / total for u in utils]


def joint_mode_probabilities(attractiveness: np.ndarray, walk_min: np.ndarray,
                             drive_min: np.ndarray, walk_pref: float,
                             alpha: float = 1.0, beta_walk: float = 0.10,
                             beta_drive: float = 0.15) -> tuple[np.ndarray, np.ndarray]:
    """Two-mode walk/drive case of joint_multimode_probabilities ->
    (p_total, p_walk). Kept as the stable seam the hand-computed unit tests
    pin; the n-mode generalization must reproduce it exactly."""
    p_total, (p_walk, _p_drive) = joint_multimode_probabilities(
        attractiveness,
        [(walk_pref, beta_walk, walk_min),
         (1.0 - walk_pref, beta_drive, drive_min)],
        alpha=alpha)
    return p_total, p_walk


def allocate_spend(category_spend: float, probabilities: np.ndarray) -> np.ndarray:
    """Dollar flow per destination; sums to category_spend when the
    probabilities sum to 1 (the invariant the tests pin)."""
    return category_spend * np.asarray(probabilities, dtype=float)
