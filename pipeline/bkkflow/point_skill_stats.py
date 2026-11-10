"""BKK-056b psk-v1 grid statistics: TOC, toroidal null, paired block bootstrap and correlogram.

New code, because oec-v1's are bound to its block-table rows (observed_extent_stats.py:120-214).
Every function reads dense block grids: ``label`` (1 positive, 0 negative, -1 unknown), named
``ranks`` on which a lower value is wetter (oec-v1's order; ``as_rank`` negates a depth), and a
boolean ``domain`` where a score is defined. With the domain set to the labelled blocks they
reproduce oec-v1's results on its fixtures. The AUC is oec-v1's own ``auc``, unchanged.

North set two rules for sparse labels on 10 November 2026 (docs/POINT_SKILL_PROTOCOL.md). A shifted
label is scored wherever it lands in the domain (Q6), and a correlogram lag counts only with at least
30 label pairs (Q7). Tested on synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

import numpy as np

from . import observed_extent_stats as oes

POSITIVE, NEGATIVE, UNKNOWN = 1, 0, -1
BLOCK_M = oes.BLOCK_M
RANGE_THRESHOLD = oes.RANGE_THRESHOLD
NOT_ESTIMABLE = oes.NOT_ESTIMABLE
MIN_LAG_PAIRS = 30  # Q7: a lag with fewer labelled pairs is never computed
RANGE_EXCEEDS_HALF_GRID = oes.PROTOCOL["interval"]["fallback"]["reason"]
NO_LAG_WITH_MIN_PAIRS = "no_lag_with_min_pairs"


def as_rank(values: Any, *, higher_is_wetter: bool) -> np.ndarray:
    """A score in oec-v1's rank order, where lower is wetter: a depth, cover or rain is negated."""
    values = np.asarray(values, dtype=float)
    return -values if higher_is_wetter else values


def auc(values: Any, positive: Any, *, higher_is_wetter: bool) -> float | None:
    """oec-v1's AUC, unchanged (Mann-Whitney, ties count 1/2), read on the score in rank order."""
    return oes.auc(as_rank(values, higher_is_wetter=higher_is_wetter), positive)


def toc(values: Any, positive: Any, *, higher_is_wetter: bool, bottom: str) -> list[dict[str, Any]]:
    """TOC points, wettest first, with thresholds in the score's own units; the bottom tie is named ``bottom``."""
    rank = as_rank(values, higher_is_wetter=higher_is_wetter).ravel()
    if np.isnan(rank).any() or np.isneginf(rank).any():
        raise ValueError("scores must be numbers or the bottom tie, never NaN or an infinite top")
    distinct, inverse = np.unique(rank, return_inverse=True)
    weights = np.asarray(positive, dtype=bool).ravel()
    hits = np.cumsum(np.bincount(inverse, weights=weights, minlength=len(distinct)))
    flagged = np.cumsum(np.bincount(inverse, minlength=len(distinct)))
    thresholds = -distinct if higher_is_wetter else distinct
    return [{"threshold": float(t) + 0.0 if np.isfinite(t) else bottom, "flagged": int(f), "hits": int(h)}
            for t, f, h in zip(thresholds, flagged, hits)]  # + 0.0 turns a negated zero back into 0.0


def _check_label(label: Any) -> np.ndarray:
    label = np.asarray(label)
    if label.ndim != 2:
        raise ValueError("label, domain and every rank must be block grids of one shape")
    if not set(np.unique(label).tolist()) <= {POSITIVE, NEGATIVE, UNKNOWN}:
        raise ValueError("labels must be 1 (positive), 0 (negative) or -1 (unknown)")
    return label


def _grids(label: Any, ranks: Mapping[str, Any], domain: Any) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    """The checked grids. A score may be NaN outside the domain, never inside it (a shifted label may land there)."""
    label, domain = _check_label(label), np.asarray(domain, dtype=bool)
    ranks = {name: np.asarray(rank, dtype=float) for name, rank in ranks.items()}
    if domain.shape != label.shape or any(rank.shape != label.shape for rank in ranks.values()):
        raise ValueError("label, domain and every rank must be block grids of one shape")
    for name, rank in ranks.items():
        if np.isnan(rank[domain]).any():
            raise ValueError(f"score {name!r} has NaN inside the domain; a block without a score is out of the case")
    return label, ranks, domain


def _check_draws(n: Any, seed: Any) -> None:
    if not all(type(value) is int for value in (n, seed)) or n < 1:  # plain ints keep the record JSON-exact
        raise ValueError(f"n and seed must be plain ints with n >= 1, not {n!r} and {seed!r}")


def _span(values: Sequence[float]) -> list[float] | None:
    return [np.min(values).item(), np.max(values).item()] if len(values) else None


def _null_summary(observed: float, shifted: list[float], prevalence: list[float], evaluable: list[int],
                  n_picks: int, seed: int) -> dict[str, Any]:
    """oec-v1's N2 summary: p = (1 + k) / (1 + n) over defined shifts, k with AUC >= observed."""
    k = int(np.sum(np.array(shifted) >= observed - 1e-12)) if shifted else 0
    return {"method": "toroidal_shift", "seed": seed, "n": n_picks, "n_undefined": n_picks - len(shifted),
            "p_ge_observed": (1 + k) / (1 + len(shifted)) if shifted else None,
            "share_ge_observed": k / len(shifted) if shifted else None,
            "prevalence_range": _span(prevalence), "evaluable_range": _span(evaluable)}


def toroidal_null(label: Any, ranks: Mapping[str, Any], domain: Any, n: int, seed: int) -> dict[str, dict[str, Any]]:
    """N2 for every score on the same shifts: labels move round the grid's torus; ranks and domain stay.

    A shifted label is scored wherever it lands in the domain (Q6). A shift whose landed labels lack a
    class is undefined for every score, so prevalence and the evaluable count vary between shifts.
    """
    _check_draws(n, seed)
    label, ranks, domain = _grids(label, ranks, domain)
    keep = domain & (label != UNKNOWN)
    found = {name: oes.auc(rank[keep], label[keep] == POSITIVE) for name, rank in ranks.items()}
    if any(value is None for value in found.values()):
        raise ValueError("the AUC is undefined in this domain, so there is nothing to test")
    observed = cast(dict[str, float], found)
    nx, ny = label.shape
    picks = np.random.default_rng(seed).choice(nx * ny - 1, size=min(n, nx * ny - 1), replace=False) + 1
    shifted: dict[str, list[float]] = {name: [] for name in ranks}
    prevalence, evaluable = [], []
    for shift in zip(*np.divmod(picks, ny)):
        moved = np.roll(label, shift, axis=(0, 1))
        both = domain & (moved != UNKNOWN)
        positive = moved[both] == POSITIVE
        if positive.all() or not positive.any():  # oec-v1's auc returns None exactly here
            continue
        for name, rank in ranks.items():
            shifted[name].append(cast(float, oes.auc(rank[both], positive)))  # both classes: never None
        prevalence.append(float(positive.mean()))
        evaluable.append(int(both.sum()))
    return {name: _null_summary(observed[name], shifted[name], prevalence, evaluable, len(picks), seed)
            for name in ranks}


def _tile_side(block_m: Any) -> int:
    if not (isinstance(block_m, int) and not isinstance(block_m, bool) and block_m > 0 and block_m % BLOCK_M == 0):
        raise ValueError(f"a bootstrap block length must be a positive multiple of {BLOCK_M} m, not {block_m!r}")
    return block_m // BLOCK_M


def _ci95(values: list[float]) -> list[float] | None:
    return [float(q) for q in np.quantile(values, [0.025, 0.975])] if values else None


def paired_block_bootstrap(label: Any, ranks: Mapping[str, Any], pairs: Iterable[tuple[str, str]], domain: Any,
                           block_m: int, n: int, seed: int) -> dict[str, Any]:
    """N3 for every score and pair on the same draws: square tiles of side ``block_m``, with replacement.

    Each score gets oec-v1's percentile 95% interval. Each (candidate, rung) pair gets the interval of
    AUC(candidate) - AUC(rung) over the same resamples. A draw without both classes is undefined for all.
    """
    side = _tile_side(block_m)
    _check_draws(n, seed)
    label, ranks, domain = _grids(label, ranks, domain)
    checked: list[tuple[str, str]] = []
    for pair in pairs:
        if len(pair) != 2 or any(name not in ranks for name in pair):
            raise ValueError(f"every pair must be (candidate, rung), two given scores, not {pair!r}")
        checked.append((pair[0], pair[1]))
    bi, bj = np.nonzero(domain & (label != UNKNOWN))
    if not bi.size:
        raise ValueError("there is no labelled block in the domain to resample")
    _, tile = np.unique((bi // side) * (label.shape[1] // side + 1) + bj // side, return_inverse=True)
    members = [np.flatnonzero(tile == t) for t in range(tile.max() + 1)]
    positive, rng = label[bi, bj] == POSITIVE, np.random.default_rng(seed)
    sampled = {name: rank[bi, bj] for name, rank in ranks.items()}
    draws: dict[str, list[float]] = {name: [] for name in ranks}
    n_defined = 0
    for _ in range(n):
        pick = np.concatenate([members[t] for t in rng.integers(len(members), size=len(members))])
        drawn = positive[pick]
        if drawn.all() or not drawn.any():  # drawn after the rng step, so the draw order stays oec-v1's
            continue
        n_defined += 1
        for name, rank in sampled.items():
            draws[name].append(cast(float, oes.auc(rank[pick], drawn)))
    return {"method": "paired_block_bootstrap", "seed": seed, "block_m": block_m, "n_tiles": len(members), "n": n,
            "n_undefined": n - n_defined, "ci95": {name: _ci95(values) for name, values in draws.items()},
            "differences": [{"candidate": a, "rung": b, "ci95": _ci95(list(np.subtract(draws[a], draws[b])))}
                            for a, b in checked]}


def correlogram(label: Any) -> dict[str, list[Any]]:
    """Label correlation between labelled blocks h apart on either axis, h = 1 .. half the shorter side.

    As oec-v1's, with each lag's pair count kept; r is computed only on lags with MIN_LAG_PAIRS pairs
    (Q7). It reads labels and positions only, never a score, so it may run at lock time. The caller
    passes labels already masked to the case's domain, as the AUC and the bootstrap see them.
    """
    label = _check_label(label)
    lags, r, pairs = [], [], []
    for h in range(1, min(label.shape) // 2 + 1):
        a = np.concatenate([label[:-h].ravel(), label[:, :-h].ravel()])
        b = np.concatenate([label[h:].ravel(), label[:, h:].ravel()])
        both = (a != UNKNOWN) & (b != UNKNOWN)
        value = np.nan
        if both.sum() >= MIN_LAG_PAIRS:
            with np.errstate(invalid="ignore", divide="ignore"):
                value = np.corrcoef(a[both], b[both])[0, 1]
        lags.append(h * BLOCK_M)
        r.append(float(value) if np.isfinite(value) else None)
        pairs.append(int(both.sum()))
    return {"lags_m": lags, "r": r, "pairs": pairs}


def range_from_correlogram(found: Mapping[str, Sequence[Any]]) -> int | str:
    """oec-v1's rule on the lags with MIN_LAG_PAIRS pairs: the first at which r <= 0.05.

    NOT_ESTIMABLE when no such lag qualifies or none falls that low (no interval, never a capped or
    guessed length). Lags that qualify but all have undefined r leave the case undefined, as in D4.
    """
    qualifying = [(lag, r) for lag, r, count in zip(found["lags_m"], found["r"], found["pairs"], strict=True)
                  if count >= MIN_LAG_PAIRS]
    for lag, r in qualifying:
        if r is not None and r <= RANGE_THRESHOLD:
            return int(lag)
    if qualifying and all(r is None for _, r in qualifying):
        raise ValueError("no correlogram lag could be computed, so neither a block length nor the fallback "
                         "is established; a case without both classes is locked as undefined")
    return NOT_ESTIMABLE


def _two_classes(label: Any) -> np.ndarray:
    label = _check_label(label)
    if not {POSITIVE, NEGATIVE} <= set(np.unique(label).tolist()):
        raise ValueError("the labels hold one class only, so the case is locked as undefined (D4), "
                         "never given a block length or the fallback")
    return label


def correlation_range_m(label: Any) -> int | str:
    """The bootstrap block length the label grid fixes before any score, or NOT_ESTIMABLE."""
    return range_from_correlogram(correlogram(_two_classes(label)))


def not_estimable_interval(label: Any) -> dict[str, Any]:
    """The fallback as locked: no interval, with every lag, r and pair count the rule examined, and why."""
    found = correlogram(_two_classes(label))
    if range_from_correlogram(found) != NOT_ESTIMABLE:
        raise ValueError("this label grid has a range, so the not-estimable fallback does not apply")
    qualifying = any(count >= MIN_LAG_PAIRS for count in found["pairs"])
    return {"method": "paired_block_bootstrap", "status": NOT_ESTIMABLE,
            "reason": RANGE_EXCEEDS_HALF_GRID if qualifying else NO_LAG_WITH_MIN_PAIRS, **found, "ci95": None}
