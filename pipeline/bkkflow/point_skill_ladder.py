"""BKK-056b psk-v1 ladder: the protocol, the lock, case assembly, evaluation and the run record.

Every candidate surface is reported against every rung of the baseline ladder (D3): its AUC, TOC,
toroidal-null p (the Chance rung) and paired block-bootstrap interval; and for the candidate against
each score rung, the paired difference with its interval. There is no claim rule (D5): the record
holds numbers and intervals only. A rung without its input is null with a reason, never dropped.
Cases, windows, seeds and block lengths are locked before any score (docs/POINT_SKILL_PROTOCOL.md).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from . import observed_extent_stats as oes
from . import point_skill as psk
from . import point_skill_stats as pss
from .point_skill_scores import scoring_window

NOT_ESTIMABLE = pss.NOT_ESTIMABLE
BOTTOM_LABEL = "bottom_tie"
KINDS = {"sensor": ("observed_wet", "observed_dry"), "report": ("reported", "not_reported")}
RUNGS: dict[str, dict[str, Any]] = {
    "exposure": {"higher_is_wetter": True, "input": "share of the block under OSM building footprints (present-day)",
                 "null_reason": "needs the building layer"},
    "channel": {"higher_is_wetter": False, "input": "distance to the MitrEarth water body and GSW permanent water mask",
                "null_reason": "needs the channel mask"},
    "rain_only": {"higher_is_wetter": True, "input": "IDW power 2 over admitted gauges with a complete accumulation",
                  "null_reason": "needs admitted event forcing (BKK-036B)"},
    "persistence": {"higher_is_wetter": True, "input": "the same kind of observation in the equal window before",
                    "null_reason": "needs a prior observation of the same kind"},
}
BY_CONSTRUCTION = ("by construction: the scenario decays from OSM water and the channel rung is the distance to the "
                   "MitrEarth and GSW mask, so both are distance-to-water ranks from different water layers; their "
                   "difference is not a finding (D6)")
LABELS = {"measures": "timed point observations against per-block scores", "is_calibration": False,
          "is_held_out_validation": False, "is_evacuation_simulation": False,
          "interpretation": "plausibility with baselines: numbers and intervals only (D5)"}
_DEFINITION = oes.PROTOCOL["definition"]

PROTOCOL: dict[str, Any] = {
    "protocol_version": psk.PROTOCOL_VERSION, "check_id": psk.CHECK_ID,
    "unit": {"crs": psk.ANALYSIS_CRS, "block_m": psk.BLOCK_M, "published_cell_m": 1000,
             "domain": "blocks every candidate evaluated over at least half their area inside the AOI"},
    "labels": {"sensor": {"wet_depth_m": psk.WET_DEPTH_M,
                          "dry_share": f"{psk.DRY_SHARE.numerator}/{psk.DRY_SHARE.denominator}",
                          "several_sensors": "wet if any is wet; dry only if every one is dry; else unknown"},
               "report": {"presence_only": True, "min_cover_m2": psk.MIN_COVER_M2,
                          "classes": "reported and not_reported, both on blocks with building cover"}},
    "definition": {"min_positives": _DEFINITION["min_observed_wet_blocks"],
                   "min_negatives": _DEFINITION["min_not_mapped_blocks"]},
    "statistic": {"auc": "oec-v1's auc unchanged: Mann-Whitney, ties count 1/2", "toc": "in the score's own units"},
    "null": {"method": "toroidal_shift", "n": 999, "seed": None,
             "domain": "a shifted label is scored wherever it lands in the case domain (Q6)"},
    "interval": {"method": "paired_block_bootstrap", "n": 999, "seed": None, "ci": "percentile 95%",
                 "block_length_rule": f"first lag with at least {pss.MIN_LAG_PAIRS} label pairs at which the "
                                      f"correlogram is <= {pss.RANGE_THRESHOLD}",
                 "fallback": {"if": "no qualifying lag falls to the threshold, or no lag has the pairs",
                              "status": NOT_ESTIMABLE, "then": "no interval; the AUC and the null are kept"}},
    "rungs": copy.deepcopy(RUNGS),
    "chance": "the toroidal-null p of each score",
    "claim_rule": None,  # D5
    "time": {"timed": "closed [t, t + lead]", "declared": "the event window",
             "persistence": "the equal-length window before the scoring window, half-open"},
    "privacy": {"reports": "aggregated to 100 m blocks at ingest; no text, photo or report id",
                "outputs": "outside Git; anything mapped by place is published at 1 km"},
    "cases": [],  # set by lock_protocol before any score
}


def _lock_candidate(candidate: Mapping[str, Any], window: tuple[Any, Any]) -> dict[str, Any]:
    name = candidate["name"]
    if name in RUNGS or name in {"bi", "bj", "label"}:
        raise ValueError(f"candidate name {name!r} is reserved")
    if scoring_window(candidate, window) != window:
        raise ValueError(f"candidate {name!r}: its scoring window must be the case window (D6)")
    entry = {"name": name, "timing": candidate["timing"], "distance_decay": bool(candidate.get("distance_decay", False))}
    if candidate["timing"] == "timed":
        entry |= {"issue_time": candidate["issue_time"].isoformat(), "lead_s": int(candidate["lead"].total_seconds())}
    return entry


def lock_protocol(cases: Sequence[Mapping[str, Any]], *, null_seed: int, interval_seed: int) -> dict[str, Any]:
    """psk-v1 with its cases, seeds and block lengths fixed before any score.

    Each case names its kind (sensor or report), area, window and candidates, and the block length from
    case_block_length (NOT_ESTIMABLE included; None only for a case its labels leave undefined).
    """
    if any(type(seed) is not int for seed in (null_seed, interval_seed)):
        raise ValueError("null_seed and interval_seed must be plain ints, fixed before any score")
    locked, seen = [], set()
    for case in cases:
        if case["case_id"] in seen:
            raise ValueError(f"case {case['case_id']!r} must be locked once")
        seen.add(case["case_id"])
        if case["kind"] not in KINDS:
            raise ValueError(f"case kind must be one of {sorted(KINDS)}")
        start, end = window = tuple(case["window"])
        if not start < end or not case["candidates"]:
            raise ValueError("a case needs a window that opens before it closes, and at least one candidate")
        block_m = case["block_m"]
        if block_m is not None and block_m != NOT_ESTIMABLE:
            pss._tile_side(block_m)
        locked.append({"case_id": case["case_id"], "kind": case["kind"], "area": case["area"],
                       "window": [start.isoformat(), end.isoformat()],
                       "candidates": [_lock_candidate(candidate, window) for candidate in case["candidates"]],
                       "block_m": block_m})
    protocol = copy.deepcopy(PROTOCOL)
    protocol["null"]["seed"], protocol["interval"]["seed"], protocol["cases"] = null_seed, interval_seed, locked
    return protocol


def assemble_case(kind: str, labels: pd.DataFrame, candidates: Mapping[str, pd.DataFrame],
                  rungs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """One case's blocks: the label (1, 0, -1 unknown), each candidate's score and each rung's value.

    The domain is the blocks every candidate's own domain holds (block_scores). A report case keeps only
    blocks with building cover, so both classes share one support (Q3) and a shifted label lands only where
    a control could be. A block without a sensor stays in a sensor case, unlabelled (Q6). A rung must have
    a value on every block of the case; a rung left out is reported null with its reason.
    """
    if kind not in KINDS or not candidates:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, with at least one candidate")
    if set(rungs) - set(RUNGS):
        raise ValueError(f"rungs must be among {sorted(RUNGS)}")
    positive_state, negative_state = KINDS[kind]
    if not set(labels["state"]) <= {positive_state, negative_state, "unknown"}:
        raise ValueError(f"{kind} labels must be {positive_state}, {negative_state} or unknown")
    case: pd.DataFrame | None = None
    for name, frame in candidates.items():
        part = frame.loc[frame["in_domain"].astype(bool), ["bi", "bj", "score"]].rename(columns={"score": name})
        case = part if case is None else case.merge(part, on=["bi", "bj"], how="inner", validate="one_to_one")
    assert case is not None
    case = case.merge(labels[["bi", "bj", "state"]], on=["bi", "bj"], how="left", validate="one_to_one")
    state = case.pop("state").fillna("unknown")
    if kind == "report":
        case, state = case[state != "unknown"], state[state != "unknown"]
    case = case.assign(label=np.select([state == positive_state, state == negative_state], [1, 0], -1))
    for name, frame in rungs.items():
        case = case.merge(frame[["bi", "bj", "value"]].rename(columns={"value": name}), on=["bi", "bj"],
                          how="left", validate="one_to_one")
        if case[name].isna().any():
            raise ValueError(f"the {name} rung needs a value on every block of the case")
    return case.sort_values(["bi", "bj"]).reset_index(drop=True)[["bi", "bj", "label", *candidates, *rungs]]


def _case_grids(case: pd.DataFrame, columns: Sequence[str]) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    if case.empty or case.duplicated(["bi", "bj"]).any():
        raise ValueError("a case needs its blocks, each listed once")
    oi = (case["bi"] - case["bi"].min()).to_numpy(dtype="int64")
    oj = (case["bj"] - case["bj"].min()).to_numpy(dtype="int64")
    shape = (int(oi.max()) + 1, int(oj.max()) + 1)
    label, domain = np.full(shape, pss.UNKNOWN), np.zeros(shape, dtype=bool)
    label[oi, oj], domain[oi, oj] = case["label"].to_numpy(), True
    grids = {}
    for column in columns:
        grids[column] = np.full(shape, np.nan)
        grids[column][oi, oj] = case[column].to_numpy(dtype=float)
    return label, domain, grids


def _status(n_positive: int, n_negative: int, definition: Mapping[str, int]) -> str:
    if not n_positive + n_negative:
        return "undefined_no_labelled_blocks"
    for count, minimum, name in ((n_positive, definition["min_positives"], "positives"),
                                 (n_negative, definition["min_negatives"], "negatives")):
        if count < max(minimum, 1):
            return f"undefined_{'too_few' if count else 'no'}_{name}"
    return "ok"


def _counts(label: np.ndarray, domain: np.ndarray) -> dict[str, int]:
    labelled = label[domain & (label != pss.UNKNOWN)]
    return {"blocks": int(domain.sum()), "positives": int((labelled == pss.POSITIVE).sum()),
            "negatives": int((labelled == pss.NEGATIVE).sum())}


def case_block_length(case: pd.DataFrame) -> int | str | None:
    """The bootstrap block length to lock, read from the labels alone before any score.

    None when the labels leave the case undefined: too few of a class, or no computable correlogram lag (D4).
    """
    label, domain, _ = _case_grids(case, [])
    counts = _counts(label, domain)
    if _status(counts["positives"], counts["negatives"], PROTOCOL["definition"]) != "ok":
        return None
    try:
        return pss.correlation_range_m(np.where(domain, label, pss.UNKNOWN))
    except ValueError:
        return None


def _absent(rung: str) -> dict[str, Any]:
    return {"status": "not_available", "reason": RUNGS[rung]["null_reason"], "auc": None, "toc": None,
            "null": None, "ci95": None}


def _difference(candidate: str, rung: str, scored: Mapping[str, Any], rungs: Mapping[str, Any],
                intervals: Mapping[tuple[str, str], Any], decay: bool) -> dict[str, Any]:
    if rungs[rung].get("status") == "not_available":
        entry = {"candidate": candidate, "rung": rung, "difference": None, "ci95": None,
                 "reason": RUNGS[rung]["null_reason"]}
    else:
        entry = {"candidate": candidate, "rung": rung, "difference": scored[candidate]["auc"] - rungs[rung]["auc"],
                 "ci95": intervals.get((candidate, rung))}
    if rung == "channel" and decay:
        entry["note"] = BY_CONSTRUCTION
    return entry


def _ladder(spec: Mapping[str, Any], protocol: Mapping[str, Any], label: np.ndarray, domain: np.ndarray,
            grids: Mapping[str, np.ndarray], names: Sequence[str], present: Sequence[str]) -> dict[str, Any]:
    wetter = {**dict.fromkeys(names, True), **{rung: RUNGS[rung]["higher_is_wetter"] for rung in present}}
    ranks = {name: pss.as_rank(grids[name], higher_is_wetter=wetter[name]) for name in grids}
    null = pss.toroidal_null(label, ranks, domain, protocol["null"]["n"], protocol["null"]["seed"])
    if spec["block_m"] == NOT_ESTIMABLE:
        if protocol["interval"].get("fallback") != PROTOCOL["interval"]["fallback"]:
            raise ValueError("an interval_not_estimable case needs psk-v1's locked fallback")
        interval, ci, paired = pss.not_estimable_interval(np.where(domain, label, pss.UNKNOWN)), {}, {}
    else:
        boot = pss.paired_block_bootstrap(label, ranks, [(c, r) for c in names for r in present], domain,
                                          spec["block_m"], protocol["interval"]["n"], protocol["interval"]["seed"])
        interval = {key: boot[key] for key in ("method", "seed", "block_m", "n_tiles", "n", "n_undefined")}
        ci, paired = boot["ci95"], {(d["candidate"], d["rung"]): d["ci95"] for d in boot["differences"]}
    keep = domain & (label != pss.UNKNOWN)
    positive = label[keep] == pss.POSITIVE

    def metrics(name: str) -> dict[str, Any]:
        values = grids[name][keep]
        return {"auc": pss.auc(values, positive, higher_is_wetter=wetter[name]),
                "toc": pss.toc(values, positive, higher_is_wetter=wetter[name], bottom=BOTTOM_LABEL),
                "null": null[name], "ci95": ci.get(name)}

    scored = {name: metrics(name) for name in names}
    rungs = {rung: metrics(rung) if rung in present else _absent(rung) for rung in RUNGS}
    decay = {c["name"]: c["distance_decay"] for c in spec["candidates"]}
    differences = [_difference(c, r, scored, rungs, paired, decay[c]) for c in names for r in RUNGS]
    return {"candidates": scored, "rungs": rungs, "differences": differences, "interval": interval}


def evaluate(case: pd.DataFrame, protocol: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    """The psk-v1 ladder for one locked case. Every metric is None for an undefined case; there is no verdict."""
    if protocol.get("protocol_version") != psk.PROTOCOL_VERSION:
        raise ValueError(f"evaluation needs the {psk.PROTOCOL_VERSION} protocol")
    locked = {c["case_id"]: c for c in protocol["cases"]}
    if case_id not in locked:
        raise ValueError(f"{case_id!r} is not a locked {psk.PROTOCOL_VERSION} case; lock before any score")
    spec = locked[case_id]
    names = [c["name"] for c in spec["candidates"]]
    if missing := [name for name in names if name not in case.columns]:
        raise ValueError(f"candidate scores {missing} are missing from the case")
    present = [rung for rung in RUNGS if rung in case.columns]
    label, domain, grids = _case_grids(case, [*names, *present])
    counts = _counts(label, domain)
    status = _status(counts["positives"], counts["negatives"], protocol["definition"])
    if status == "ok" and spec["block_m"] is None:
        if case_block_length(case) is not None:
            raise ValueError(f"the bootstrap block length for {case_id!r} is not locked in the protocol")
        status = "undefined_no_correlogram_lag"
    result = {"case_id": case_id, "kind": spec["kind"], "status": status, "counts": counts,
              "candidates": None, "rungs": None, "differences": None, "interval": None}
    if status != "ok":
        return result
    return {**result, **_ladder(spec, protocol, label, domain, grids, names, present)}


def build_record(*, run_id: str, protocol: Mapping[str, Any], results: Sequence[Mapping[str, Any]],
                 code_identity: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The run record: the locked protocol and each case's results, case-level only (no block leaves it, D1)."""
    if protocol.get("protocol_version") != psk.PROTOCOL_VERSION:
        raise ValueError(f"a record needs the {psk.PROTOCOL_VERSION} protocol")
    locked = {case["case_id"] for case in protocol["cases"]}
    if any(result["case_id"] not in locked for result in results):
        raise ValueError("every result must come from a locked case")
    return {"check_id": psk.CHECK_ID, "protocol_version": psk.PROTOCOL_VERSION, "run_id": run_id,
            "protocol": copy.deepcopy(dict(protocol)), "results": copy.deepcopy(list(results)),
            "labels": dict(LABELS), "code_identity": copy.deepcopy(code_identity)}


def record_json(record: Mapping[str, Any]) -> str:
    """The record as canonical JSON: sorted keys, no NaN or infinity, so fixed seeds give identical bytes."""
    return json.dumps(record, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
