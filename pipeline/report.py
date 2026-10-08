"""Generate review figures for a completed run.

Figures are evidence, not decoration: every panel states what it shows, which
run it came from and what the model status is. Nothing here is a publication
graphic and no figure may be read without its caption.

    python pipeline/report.py <saved_run_a> <saved_run_b>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bkkflow.aoi import load_aoi  # noqa: E402
from bkkflow import replay_audit  # noqa: E402
from bkkflow.util import RUNS_DIR, ensure_dir  # noqa: E402

STATUS_COLOUR = {
    "demonstration": "#b45309",
    "research": "#1d4ed8",
    "reviewed": "#15803d",
    "operational": "#7c3aed",
}


@dataclass(frozen=True)
class CheckedRun:
    """One immutable run bound to a fresh successful replay audit."""

    run_id: str
    state: str
    bundle: replay_audit.AuditBundle
    audit: dict[str, Any]


@dataclass(frozen=True)
class CheckedPair:
    """A dry/moderate pair whose common research contract is identical."""

    aoi_id: str
    aoi_label: str
    dry: CheckedRun
    moderate: CheckedRun
    audit_status: str


def _audited_run(run_id: str) -> CheckedRun:
    if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id:
        raise ValueError("pair run ID is invalid")
    root = RUNS_DIR.resolve()
    run_dir = (root / run_id).resolve()
    if not run_dir.is_relative_to(root):
        raise ValueError("pair run path escapes runs directory")
    audit = replay_audit.audit_saved_run(run_dir)
    if audit.get("status") != "PASS":
        detail = "; ".join(
            str(check.get("detail", check.get("name", "failed check")))
            for check in audit.get("checks", [])
            if isinstance(check, dict) and check.get("status") == "FAIL"
        )
        raise ValueError(f"pair audit failed for {run_id}: {detail or 'unknown failure'}")
    bundle = replay_audit.load_audit_bundle(run_dir)
    if (
        audit.get("run_id") != bundle.run_id
        or audit.get("aoi_id") != bundle.aoi_id
        or audit.get("audited_hashes") != bundle.file_hashes
    ):
        raise ValueError(f"pair audit binding mismatch for {run_id}")
    state = bundle.manifest["active_scenario"]["state"]
    return CheckedRun(bundle.run_id, state, bundle, audit)


def _require_equal(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ValueError(f"pair {label} mismatch")


def _cohort_rows(run: CheckedRun) -> pd.DataFrame:
    columns = ["person_id", "order_id", "weight", "sampling_probability"]
    frame = run.bundle.tables["cohort"]
    if not set(columns) <= set(frame):
        raise ValueError("pair cohort IDs/weights mismatch")
    return frame[columns].sort_values(["person_id", "order_id"]).reset_index(drop=True)


def _common_contract(run: CheckedRun) -> dict[str, Any]:
    bundle, manifest, stats = run.bundle, run.bundle.manifest, run.bundle.stats
    rows = manifest["evacuation_scenario"]["destinations"]
    identifiers = [row["dest_id"] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("pair evacuation assumptions mismatch")
    evacuation = {**manifest["evacuation_scenario"], "destinations": []}
    flood = manifest["flood_scenario"]
    state_parameters = {"severity", "peak_depth_m", "decay_length_m", "duration_h"}
    flood = {
        **{key: value for key, value in flood.items() if key != "parameters"},
        "parameters": {key: value for key, value in flood["parameters"].items()
                       if key not in state_parameters},
    }
    contract = bundle.denominators
    quantities = contract["quantities"]
    return {
        "AOI label": stats["geography"]["name"],
        "geography contract": manifest["geography"],
        "statistics geography": stats["geography"],
        "validation status": manifest["validation_status"],
        "source/code identity": (manifest["code_identity"], manifest["source_versions"]),
        "source summary": stats["sources"],
        "validation result": stats["validation"],
        "population assumptions": manifest["population_model"],
        "PFLOW assumptions": manifest["pflow_contract"],
        "configured flood assumptions": flood,
        "evacuation assumptions": (evacuation, sorted(rows, key=lambda row: row["dest_id"])),
        "cohort identity": tuple(
            bundle.cohort_metadata[key] for key in replay_audit.COHORT_IDENTITY_FIELDS
        ),
        "denominator contract": {
            "contract_version": contract["contract_version"],
            "scope": contract["scope"],
            "capacity": contract["capacity"],
            "denominator_assignment": contract["pairing"]["denominator_assignment"],
            "common_identity": contract["pairing"]["common_identity"],
        },
        "denominator F/S/P/C quantities": tuple(
            quantities[key] for key in ("full_population", "sample", "present", "cohort")
        ),
        "population quantities": {
            key: value for key, value in stats["population"].items()
            if key not in {"people_exposed", "exposed_share_of_present"}
        },
    }


def load_checked_pair(first_run_id: str, second_run_id: str) -> CheckedPair:
    """Freshly audit and bind exactly one dry and one moderate saved run."""
    if first_run_id == second_run_id:
        raise ValueError("pair requires two distinct run IDs")
    runs = [_audited_run(first_run_id), _audited_run(second_run_id)]
    by_state = {run.state: run for run in runs}
    if len(by_state) != 2 or set(by_state) != {"dry", "moderate"}:
        raise ValueError("pair must contain exactly one dry and one moderate run")
    dry, moderate = by_state["dry"], by_state["moderate"]
    if dry.bundle.cohort_metadata.get("reference_run_id") is not None:
        raise ValueError("dry cohort must be an independent pair baseline")
    if moderate.bundle.cohort_metadata.get("reference_run_id") != dry.run_id:
        raise ValueError("moderate cohort must reference dry run")

    _require_equal("AOI identity", dry.bundle.aoi_id, moderate.bundle.aoi_id)
    dry_flood = dry.bundle.manifest["flood_scenario"]["parameters"]
    moderate_flood = moderate.bundle.manifest["flood_scenario"]["parameters"]
    if dry_flood["peak_depth_m"] != 0 or moderate_flood["peak_depth_m"] <= 0:
        raise ValueError("pair flood state identity mismatch")
    dry_common, moderate_common = _common_contract(dry), _common_contract(moderate)
    for label in dry_common:
        _require_equal(label, dry_common[label], moderate_common[label])
    if not _cohort_rows(dry).equals(_cohort_rows(moderate)):
        raise ValueError("pair cohort IDs/weights mismatch")
    return CheckedPair(
        dry.bundle.aoi_id, dry.bundle.stats["geography"]["name"], dry, moderate, "PASS"
    )


BANNED_PAIR_CLAIMS = (
    "isolates the flood term",
    "flood caused the change",
    "representative of bangkok",
    "operationally safe",
    "predicts evacuation safety",
)


def _validate_evidence_language(text: str) -> None:
    lowered = text.casefold()
    for claim in BANNED_PAIR_CLAIMS:
        if claim in lowered:
            raise ValueError(f"banned evidence claim: {claim}")


def _cell(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        value = f"{value:.12g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _safe_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return token or "area"


def write_pair_evidence(pair: CheckedPair, report_dir: Path) -> Path:
    """Write a denominator-explicit, non-causal evidence record from a checked pair."""
    if not isinstance(pair, CheckedPair) or pair.audit_status != "PASS":
        raise ValueError("pair evidence requires a PASS CheckedPair")
    dry, moderate = pair.dry, pair.moderate
    runs = (("dry", dry), ("moderate", moderate))
    manifest = dry.bundle.manifest
    departure = manifest["evacuation_scenario"]["departure_model"]
    cohort = dry.bundle.cohort_metadata
    denominator = dry.bundle.denominators
    code = manifest["code_identity"]
    lines = [
        f"# {pair.aoi_label} dry–moderate saved-pair evidence",
        "",
        f"AOI: **{pair.aoi_label}** (`{pair.aoi_id}`). Pair audit status: **PASS**.",
        "This is a within-model fixed-declared-assumption contrast. It is not causal, "
        "not predictive, not operational, and not safety guidance.",
        "",
        "## Run and audit identity",
        "",
        "| Active state | Run ID | Audit | manifest.json SHA-256 | stats.json SHA-256 |",
        "|---|---|---:|---|---|",
    ]
    for state, run in runs:
        hashes = run.audit["audited_hashes"]
        lines.append(
            f"| {state} | `{run.run_id}` | {run.audit['status']} | "
            f"`{hashes['manifest.json']}` | `{hashes['stats.json']}` |"
        )
    lines += ["", "Audited artifact hashes:", ""]
    for state, run in runs:
        for name, digest in sorted(run.audit["audited_hashes"].items()):
            lines.append(f"- `{state}:{_cell(name)}`: `{digest}`")

    lines += [
        "",
        "## Common source, code, and configuration identity",
        "",
        f"- Code commit: `{code['git_commit']}`; tree: `{code['git_tree']}`; "
        f"source digest: `{code['source_sha256']}`.",
        f"- Population version: `{manifest['population_model']['population_version']}`; "
        f"PFLOW contract: `{manifest['pflow_contract']['contract_version']}`.",
        f"- Configured flood scenario: "
        f"`{manifest['active_scenario']['configured_scenario_id']}`; model: "
        f"`{manifest['flood_scenario']['model_name']}` "
        f"v{manifest['flood_scenario']['model_version']}.",
        f"- Cohort digest: `{cohort['cohort_digest']}`; sample digest: "
        f"`{cohort['sample_digest']}`.",
        f"- Denominator contract: `{denominator['contract_version']}`; capacity: "
        f"`{denominator['capacity']['method']}` using "
        f"`{denominator['capacity']['integerization_rule']}`.",
        "",
        "Source versions:",
        "",
        "| Source ID | Content SHA-256 | Retrieved at |",
        "|---|---|---|",
    ]
    for source in manifest["source_versions"]:
        lines.append(
            f"| `{_cell(source['source_id'])}` | `{source['content_sha256']}` | "
            f"{_cell(source.get('retrieved_at'))} |"
        )

    meanings = {
        "F": ("full population", "input weighted resident-agent table"),
        "S": ("deterministic sample", "F"),
        "P": ("people present", "S"),
        "E": ("exposed present", "P"),
        "C": ("fixed evacuation cohort", "P"),
        "A": ("arrived", "C; clearance uses A only"),
    }

    def quantities(run: CheckedRun) -> dict[str, tuple[int, int, Any]]:
        values = run.bundle.denominators["quantities"]
        result = {
            key: (values[name]["rows"], values[name]["rows"], values[name]["weight"])
            for key, name in (("F", "full_population"), ("S", "sample"),
                              ("P", "present"), ("E", "exposed_present"),
                              ("C", "cohort"))
        }
        arrived = values["terminal_states"]["arrived"]
        result["A"] = (arrived["outcome_records"], arrived["source_rows"], arrived["weight"])
        return result

    dry_q, moderate_q = quantities(dry), quantities(moderate)
    lines += [
        "",
        "## F/S/P/E/C/A quantities and denominators",
        "",
        "| Code | Quantity | Denominator | Dry records | Dry source rows | Dry weight | "
        "Moderate records | Moderate source rows | Moderate weight |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, (meaning, basis) in meanings.items():
        lines.append(
            f"| `{key}` | {meaning} | {basis} | "
            f"{_cell(dry_q[key][0])} | {_cell(dry_q[key][1])} | {_cell(dry_q[key][2])} | "
            f"{_cell(moderate_q[key][0])} | {_cell(moderate_q[key][1])} | "
            f"{_cell(moderate_q[key][2])} |"
        )
    lines += [
        "",
        f"- E/P exposure share — dry: "
        f"{_cell(dry.bundle.denominators['shares']['exposed_of_present'])}; moderate: "
        f"{_cell(moderate.bundle.denominators['shares']['exposed_of_present'])}.",
        f"- Declared assignments: exposure = "
        f"{denominator['pairing']['denominator_assignment']['exposure']}; terminal states = "
        f"{denominator['pairing']['denominator_assignment']['terminal_states']}; clearance = "
        f"{denominator['pairing']['denominator_assignment']['clearance']}.",
        "",
        "## Terminal outcomes over C",
        "",
        "| Terminal state | Dry records | Dry source rows | Dry weight | Dry share/C | "
        "Moderate records | Moderate source rows | Moderate weight | Moderate share/C |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for state in replay_audit.TERMINAL_STATES:
        dry_term = dry.bundle.denominators["quantities"]["terminal_states"][state]
        moderate_term = moderate.bundle.denominators["quantities"]["terminal_states"][state]
        lines.append(
            f"| `{state}` | {dry_term['outcome_records']} | {dry_term['source_rows']} | "
            f"{_cell(dry_term['weight'])} | "
            f"{_cell(dry.bundle.denominators['shares']['terminal_of_cohort'][state])} | "
            f"{moderate_term['outcome_records']} | {moderate_term['source_rows']} | "
            f"{_cell(moderate_term['weight'])} | "
            f"{_cell(moderate.bundle.denominators['shares']['terminal_of_cohort'][state])} |"
        )

    lines += [
        "",
        "## Arrived-only clearance over A",
        "",
        "| Quantile | Dry minutes | Moderate minutes |",
        "|---|---:|---:|",
    ]
    for label, key in (("p5", "p5"), ("p50", "median"), ("p95", "p95")):
        lines.append(
            f"| {label} | {_cell(dry.bundle.stats['evacuation']['clearance_time_minutes'][key])} | "
            f"{_cell(moderate.bundle.stats['evacuation']['clearance_time_minutes'][key])} |"
        )
    lines += ["", "## Conservation", "", "| State | cohort_weight | terminal_weight | residual_abs | tolerance | passed |",
              "|---|---:|---:|---:|---:|---:|"]
    for state, run in runs:
        conservation = run.bundle.denominators["conservation"]
        lines.append(
            f"| {state} | {_cell(conservation['cohort_weight'])} | "
            f"{_cell(conservation['terminal_weight'])} | {_cell(conservation['residual_abs'])} | "
            f"{_cell(conservation['absolute_tolerance'])} | {conservation['passed']} |"
        )

    destination_rows = {
        state: {item["dest_id"]: item for item in run.bundle.stats["evacuation"]["destinations"]}
        for state, run in runs
    }
    lines += [
        "",
        "## Hypothetical destination capacity",
        "",
        "All destinations are `hypothetical_unverified`; capacity is a model assumption.",
        "",
        "| Destination ID | Capacity | Dry admitted integer units | Dry remaining | "
        "Moderate admitted integer units | Moderate remaining |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for destination in sorted(destination_rows["dry"]):
        dry_destination = destination_rows["dry"][destination]
        moderate_destination = destination_rows["moderate"][destination]
        capacity = dry_destination["capacity"]
        lines.append(
            f"| `{_cell(destination)}` | {capacity} | {capacity - dry_destination['remaining']} | "
            f"{dry_destination['remaining']} | {capacity - moderate_destination['remaining']} | "
            f"{moderate_destination['remaining']} |"
        )

    compliance = departure["compliance"]
    lines += [
        "",
        "## Executed and unexecuted sensitivities",
        "",
        f"- Executed: one active dry baseline and one active moderate scenario at compliance "
        f"{_cell(compliance)} with the same saved cohort and declared assumptions.",
        "- Explicitly not executed: non-zero low-severity and high-severity flood "
        "sensitivities, and compliance sensitivities 0.60 and 0.90.",
        "- This is incomplete sensitivity evidence; no uncertainty envelope or local "
        "calibration interval is available.",
        "",
        "## Interpretation limits",
        "",
        "- Population quantities are sample-only, with no reweighting to an external control "
        "total; this is not a district or Bangkok total and is non-representative beyond the "
        "deterministic sample.",
        "- Flood depth is a non-hydraulic scenario surface without citywide terrain, drainage, "
        "pumps, tide, subsidence, or conserved runoff physics.",
        "- Mobility and evacuation behaviour are uncalibrated scenario priors.",
        "- Destinations and capacities are hypothetical and unverified; admitted and remaining "
        "values are model-accounting quantities.",
        "- The contrast holds declared assumptions fixed but is not causal and does not estimate "
        "an observed intervention effect.",
        "- Results are not predictive, not operational, and not safety guidance.",
        "- Sensitivity coverage is incomplete sensitivity evidence: low/high forcing and "
        "compliance 0.60/0.90 were not run.",
        "- Saved hashes document provenance and integrity, not external-source authenticity.",
        "",
    ]
    text = "\n".join(lines)
    _validate_evidence_language(text)
    path = ensure_dir(Path(report_dir)) / f"{_safe_token(pair.aoi_label)}-pair-evidence.md"
    path.write_text(text, encoding="utf-8")
    return path


def _checked_table(run: CheckedRun, role: str) -> pd.DataFrame:
    if role in run.bundle.tables:
        return run.bundle.tables[role].copy()
    output = run.bundle.outputs.get(role)
    if output is None:
        raise ValueError(f"checked report role is missing: {role}")
    path = run.bundle.run_dir / output["uri"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    if digest != run.audit["audited_hashes"].get(output["uri"]):
        raise ValueError(f"checked report artifact changed after audit: {role}")
    return pd.read_parquet(path)


def _caption(figure, run_id: str, status: str, extra: str = "") -> None:
    figure.text(
        0.01,
        0.01,
        f"BKK/FLOW run {run_id[:8]} | validation status: {status} | "
        f"demonstration output, not a forecast or warning product. {extra}",
        fontsize=7.5,
        color="#444444",
        ha="left",
    )


def figure_scenario_overview(run: CheckedRun, report_dir: Path) -> list[Path]:
    """Population, flood depth, closed edges and outcomes in one figure."""
    manifest, stats = run.bundle.manifest, run.bundle.stats
    status = manifest["validation_status"]
    aoi = load_aoi(manifest["geography"]["aoi_id"]).to_crs("EPSG:32647")
    edges = _checked_table(run, "network_edges")
    flood = _checked_table(run, "flood_slices")
    buildings = _checked_table(run, "buildings")
    peak_time = manifest["flood_scenario"]["parameters"]["peak_time_s"]
    area_label = stats["geography"]["name"]

    figure, axes = plt.subplots(2, 2, figsize=(14, 11))
    figure.suptitle(
        f"BKK/FLOW pilot scenario overview — {area_label}, Bangkok\n"
        f"scenario: {manifest['flood_scenario']['parameters']['scenario_id']} "
        f"(severity {manifest['flood_scenario']['parameters']['severity']}, "
        f"source role: {manifest['flood_scenario']['parameters']['source_role']})",
        fontsize=13,
    )

    # 1. Scenario depth surface.
    axis = axes[0][0]
    peak = flood[flood["time_s"] == peak_time] if len(flood) else flood
    if len(peak):
        points = axis.scatter(
            peak["x"], peak["y"], c=peak["depth_m"], s=6, cmap="Blues", vmin=0, vmax=max(peak["depth_m"].max(), 0.01)
        )
        figure.colorbar(points, ax=axis, label="scenario depth (m)", fraction=0.046)
    axis.set_title("Flood depth — SCENARIO, not observed or modelled")
    _draw_aoi(axis, aoi)

    # 2. Walk network closed at peak.
    axis = axes[0][1]
    if len(edges) and "geometry_wkt" in edges:
        from shapely import wkt

        geoms = edges["geometry_wkt"].map(wkt.loads)
        closed_ids = set()
        states = _checked_table(run, "edge_states")
        if len(states):
            walk = states[(states["time_s"] == peak_time) & (states["mode"] == 0)]
            closed_ids = set(walk[walk["closed"]]["edge_id"])
        for edge_id, geometry in zip(edges["edge_id"], geoms):
            closed = edge_id in closed_ids
            axis.plot(
                *geometry.xy,
                color="#b91c1c" if closed else "#9ca3af",
                linewidth=1.5 if closed else 0.5,
                zorder=2 if closed else 1,
            )
        axis.set_title(
            f"Pedestrian network at peak — {len(closed_ids)} closed / {len(edges)} ways"
        )
    _draw_aoi(axis, aoi)

    # 3. Building exposure by modelled depth.
    axis = axes[1][0]
    if len(buildings) and "geometry_wkt" in buildings:
        from shapely import wkt

        import geopandas as gpd

        geoms = buildings["geometry_wkt"].map(wkt.loads)
        # Normalise to 0-1 so the colour scale is comparable between runs;
        # geopandas' plot() forwards unknown kwargs to the artist.
        depth = buildings["max_depth_m"].fillna(0.0).astype(float)
        span = float(depth.max()) or 1.0
        frame = gpd.GeoDataFrame(
            {"exposure": np.clip(depth / span, 0.0, 1.0), "geometry": list(geoms)},
            geometry="geometry",
            crs="EPSG:32647",
        )
        frame.plot(column="exposure", ax=axis, cmap="YlOrRd", legend=True, linewidth=0)
        axis.set_title(
            f"Building exposure by scenario depth (0 to {span:.2f} m) — exposure only, not refuge status",
            fontsize=10,
        )
    _draw_aoi(axis, aoi)

    # 4. Evacuation outcomes.
    axis = axes[1][1]
    distribution = stats["evacuation"]["state_distribution"]
    if distribution:
        names = list(distribution)
        values = [distribution[name] for name in names]
        colours = ["#15803d" if name == "arrived" else "#b45309" for name in names]
        bars = axis.barh(names, values, color=colours)
        axis.bar_label(bars, fmt="%.0f", fontsize=8)
        axis.set_xlabel("weighted people")
    axis.set_title("Evacuation outcomes — all destinations are hypothetical")
    clearance = stats["evacuation"]["clearance_time_minutes"]
    if clearance.get("median") is not None:
        axis.text(
            0.02,
            0.97,
            f"Clearance minutes: p5 {clearance['p5']}, median {clearance['median']}, p95 {clearance['p95']}",
            transform=axis.transAxes,
            fontsize=8.5,
            va="top",
        )

    # Only the map panels keep a fixed aspect; a bar chart must not be forced
    # into one or it collapses to a strip.
    for position in ((0, 0), (0, 1), (1, 0)):
        axes[position[0]][position[1]].set_aspect("equal")
        axes[position[0]][position[1]].set_xticks([])
        axes[position[0]][position[1]].set_yticks([])
    axes[1][1].tick_params(axis="x", labelsize=8)

    _caption(
        figure,
        run.run_id,
        status,
        f"Area {area_label}. Residents {stats['population']['residents_weighted']:,.0f}; present "
        f"{stats['population']['people_present']:,.0f}; exposed "
        f"{stats['population']['people_exposed']:,.0f}.",
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.95))
    path = report_dir / f"{_safe_token(area_label)}-{run.state}-overview.png"
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return [path]


def figure_comparison(pair: CheckedPair, report_dir: Path) -> list[Path]:
    """Dry versus moderate clearance and outcomes for an audited checked pair."""
    moderate, dry = pair.moderate.bundle.stats, pair.dry.bundle.stats
    status = moderate["validation_status"]

    states = list(replay_audit.TERMINAL_STATES)
    dry_states = dry["evacuation"].get("state_distribution", {})
    moderate_states = moderate["evacuation"].get("state_distribution", {})

    figure, axes = plt.subplots(1, 2, figsize=(14, 5.8))
    figure.suptitle(
        f"Dry baseline versus moderate scenario — {pair.aoi_label}, Bangkok",
        fontsize=13,
    )

    positions = np.arange(len(states))
    width = 0.38
    axes[0].bar(
        positions - width / 2,
        [dry_states.get(state, 0.0) for state in states],
        width,
        label="dry baseline",
        color="#9ca3af",
    )
    axes[0].bar(
        positions + width / 2,
        [moderate_states.get(state, 0.0) for state in states],
        width,
        label="moderate scenario",
        color="#b45309",
    )
    axes[0].set_xticks(positions)
    axes[0].set_xticklabels([state.replace("_", "\n") for state in states])
    axes[0].set_ylabel("weighted people")
    axes[0].legend()
    axes[0].set_title("Evacuation state distribution")
    axes[0].tick_params(axis="x", labelsize=8.5)

    dry_failed = dry_states.get("route_failed", 0.0)
    moderate_failed = moderate_states.get("route_failed", 0.0)
    axes[1].bar(
        [0, 1],
        [dry["flood"]["edges_closed"], moderate["flood"]["edges_closed"]],
        color=["#9ca3af", "#b45309"],
        width=0.5,
    )
    axes[1].set_xticks([0, 1])
    axes[1].set_xticklabels(["dry baseline", "moderate"])
    axes[1].set_ylabel("ways closed at peak")
    axes[1].set_title("Network disruption at peak")
    axes[1].text(
        0.5,
        0.94,
        f"route_failed: {dry_failed:,.0f} dry  →  {moderate_failed:,.0f} moderate\n"
        f"clearance p95: {dry['evacuation']['clearance_time_minutes'].get('p95')} min  →  "
        f"{moderate['evacuation']['clearance_time_minutes'].get('p95')} min",
        transform=axes[1].transAxes,
        fontsize=8.5,
        ha="center",
        va="top",
    )

    _caption(
        figure,
        pair.moderate.run_id,
        status,
        f"Area {pair.aoi_label}. Dry run {pair.dry.run_id[:8]}; "
        f"moderate run {pair.moderate.run_id[:8]}. "
        "This is a within-model fixed-declared-assumption contrast over sample denominators; "
        "behaviours are uncalibrated priors and the comparison is not causal.",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.93))
    path = report_dir / f"{_safe_token(pair.aoi_label)}-dry-vs-moderate.png"
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return [path]


def figure_present_profile(run: CheckedRun, report_dir: Path) -> list[Path]:
    """Present population over 24 hours, distinguishing resident from present."""
    mesh = _checked_table(run, "mesh_volume")
    if mesh.empty:
        return []
    hourly = (
        mesh.assign(hour=(mesh["time_s"] // 3600).astype(int))
        .groupby("hour", as_index=False)["total_pop"]
        .sum()
    )
    persons = _checked_table(run, "persons")
    residents = float(persons["weight"].sum()) if len(persons) else np.nan
    area_label = run.bundle.stats["geography"]["name"]

    figure, axis = plt.subplots(figsize=(11, 5))
    axis.plot(hourly["hour"], hourly["total_pop"], marker="o", color="#1d4ed8", label="people present (sampled, weighted)")
    axis.axhline(residents, color="#6b7280", linestyle="--", label="resident baseline (weighted)")
    axis.set_xlabel("hour of day")
    axis.set_ylabel("weighted people")
    axis.set_title(
        f"Present population versus resident baseline — {area_label}; different quantities"
    )
    axis.legend()
    axis.grid(alpha=0.3)
    _caption(
        figure, run.run_id, run.bundle.manifest["validation_status"],
        f"Area {area_label}. Presence comes from scenario activity priors, not observation.",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    path = report_dir / f"{_safe_token(area_label)}-{run.state}-present-profile.png"
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return [path]


def _draw_aoi(axis, aoi) -> None:
    boundary = aoi.geometry.union_all().exterior
    xs, ys = boundary.xy
    axis.plot(xs, ys, color="#111827", linewidth=1.4, zorder=5)
    axis.set_aspect("equal")
    axis.set_xticks([])
    axis.set_yticks([])


def write_summary(run_id: str, report_dir: Path, figures: list[Path], baseline_id: str | None) -> Path:
    stats = json.loads((RUNS_DIR / run_id / "stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUNS_DIR / run_id / "manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((RUNS_DIR / run_id / "validation.json").read_text(encoding="utf-8"))
    population_qa = json.loads((RUNS_DIR / run_id / "population_qa.json").read_text(encoding="utf-8"))

    lines = [
        f"# BKK/FLOW pilot run `{run_id}`",
        "",
        f"**Validation status: {manifest['validation_status']}** — demonstration output. "
        "This is not a forecast, a warning product, or evacuation advice.",
        "",
        "## Geography",
        "",
        f"- Area of interest: {stats['geography']['name']} (`{stats['geography']['aoi_id']}`), "
        f"{stats['geography']['area_km2']} km²",
        f"- Analysis CRS: `{stats['geography']['analysis_crs']}`; storage CRS: `OGC:CRS84`",
        f"- AOI version: `{manifest['geography']['aoi_version']}`",
        "",
        "## Population (five distinct quantities)",
        "",
        f"- Resident baseline (weighted): {stats['population']['residents_weighted']:,.0f}",
        f"- People present at the analysis time: {stats['population']['people_present']:,.0f}",
        f"- People exposed to scenario flood: {stats['population']['people_exposed']:,.0f} "
        f"({stats['population']['exposed_share_of_present']:.1%} of present)",
        f"- Evacuation cohort: {stats['evacuation']['cohort_weighted']:,.0f}",
        f"- Population version: `{stats['population']['population_version']}`",
        "",
        f"External control-total error: **{population_qa['control_error']['status']}** "
        f"({population_qa['control_error'].get('reason', '')})",
        "",
        "## Flood",
        "",
        f"- Model: `{stats['flood']['model']['name']}` v{stats['flood']['model']['version']}, "
        f"source role **{stats['flood']['source_role']}**",
        f"- Peak scenario depth: {stats['flood']['max_depth_m']} m",
        f"- Area at or above 0.15 m: {stats['flood']['flooded_area_km2']} km² "
        f"({stats['flood']['flooded_area_basis']})",
        f"- Ways closed at peak (pedestrian): {stats['flood']['edges_closed']:,} of {stats['flood']['edges_total']:,}",
        f"- Buildings with scenario water: {stats['flood']['flooded_buildings']:,}",
        "",
        "## Evacuation",
        "",
        f"- Arrived: {stats['evacuation']['arrived_weighted']:,.0f}",
        f"- Unserved: {stats['evacuation']['unserved_weighted']:,.0f}",
    ]
    clearance = stats["evacuation"]["clearance_time_minutes"]
    if clearance.get("median") is not None:
        lines.append(
            f"- Clearance time (minutes): p5 {clearance['p5']}, median {clearance['median']}, p95 {clearance['p95']}"
        )
    lines += [
        "",
        "State distribution:",
        "",
    ]
    for state, value in sorted(stats["evacuation"].get("state_distribution", {}).items()):
        lines.append(f"- `{state}`: {value:,.0f}")
    lines += [
        "",
        f"Destinations: {len(stats['evacuation'].get('destinations', []))}, "
        "**all hypothetical and unverified**. No refuge claim is made by this run.",
        "",
        "## Validation",
        "",
        f"- Checks: {validation['checks_total']} total, {validation['checks_failed']} failed",
        f"- Result: {'PASS' if validation['passed'] else 'FAIL'}",
        "",
        "## Warnings carried by this run",
        "",
    ]
    for warning in stats.get("warnings", []):
        lines.append(f"- {warning}")
    if baseline_id:
        lines += ["", f"Baseline (dry) comparison run: `{baseline_id}`.", ""]
    lines += ["## Figures", ""]
    for figure in figures:
        lines.append(f"- `{figure.name}`")
    lines += ["", "---", "", "Prepared by the BKK/FLOW research pipeline. Demonstration status.", ""]

    path = report_dir / "SUMMARY.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def publish_pair_report(first_run_id: str, second_run_id: str) -> dict[str, Any]:
    """Atomically publish figures and evidence only after the pair passes every gate."""
    pair = load_checked_pair(first_run_id, second_run_id)
    target_name = (
        f"{_safe_token(pair.aoi_label)}-pair-report-"
        f"{_safe_token(pair.dry.run_id)}-{_safe_token(pair.moderate.run_id)}"
    )
    target = pair.moderate.bundle.run_dir / target_name
    if target.exists():
        raise ValueError(f"pair report already exists: {target.name}")

    with tempfile.TemporaryDirectory(
        prefix=".pair-report-", dir=pair.moderate.bundle.run_dir
    ) as temporary:
        scratch = Path(temporary)
        figures = [
            *figure_scenario_overview(pair.moderate, scratch),
            *figure_present_profile(pair.moderate, scratch),
            *figure_comparison(pair, scratch),
        ]
        evidence = write_pair_evidence(pair, scratch)
        artifacts = [*figures, evidence]
        if (
            len(figures) != 3
            or len({path.name for path in artifacts}) != len(artifacts)
            or any(path.parent != scratch or not path.is_file() or path.stat().st_size == 0
                   for path in artifacts)
        ):
            raise ValueError("pair report artifact check failed")
        _validate_evidence_language(evidence.read_text(encoding="utf-8"))
        scratch.replace(target)

    return {
        "report_dir": str(target),
        "figures": [str(target / path.name) for path in figures],
        "evidence": str(target / evidence.name),
        "dry_run_id": pair.dry.run_id,
        "moderate_run_id": pair.moderate.run_id,
        "audit_status": pair.audit_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_ids", nargs=2, metavar="RUN")
    args = parser.parse_args()
    try:
        result = publish_pair_report(*args.run_ids)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"pair report failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
