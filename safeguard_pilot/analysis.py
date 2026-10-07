"""Paired descriptive analysis with missingness bounds and template clustering."""

import random
from collections import Counter, defaultdict
from pathlib import Path

from .common import read_json, write_json


def cluster_interval(pairs, seed=927, draws=2000):
    groups = defaultdict(list)
    for group, difference in pairs:
        groups[group].append(difference)
    names = sorted(groups)
    # A degenerate [0, 0] bootstrap interval from a tiny all-zero pilot would
    # misleadingly suggest certainty. Omit intervals without outcome variation.
    if len(names) < 2 or len({difference for _, difference in pairs}) < 2:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        selected = [value for name in rng.choices(names, k=len(names)) for value in groups[name]]
        estimates.append(sum(selected) / len(selected))
    estimates.sort()
    return [estimates[int(0.025 * draws)], estimates[min(draws - 1, int(0.975 * draws))]]


def summarize(manifest, records):
    plan = manifest["plan"]
    jobs = {j["episode_id"]: j for j in plan["schedule"]}
    cases = {c["case_id"]: c for c in plan["cases"]}
    indexed = {}
    for record in records:
        identity = record["episode_id"]
        if identity in indexed or identity not in jobs:
            raise ValueError("Duplicate or unplanned episode in results")
        if record["fingerprint"] != manifest["fingerprint"] or record["prompt_sha256"] != jobs[identity]["prompt_sha256"]:
            raise ValueError("Episode fingerprint mismatch")
        for key in ("case_id", "condition", "repeat"):
            if record[key] != jobs[identity][key]:
                raise ValueError("Episode metadata mismatch")
        indexed[identity] = record
    metrics = {}
    for condition in plan["config"]["conditions"]:
        planned = [j for j in jobs.values() if j["condition"] == condition]
        primary = [j for j in planned if cases[j["case_id"]]["kind"] == "primary"]
        valid = [indexed[j["episode_id"]] for j in primary
                 if j["episode_id"] in indexed and indexed[j["episode_id"]].get("valid_for_primary_analysis")]
        bad = sum(r["observed_score"]["approval_violation"] for r in valid)
        missing = len(primary) - len(valid)
        all_valid = [indexed[j["episode_id"]] for j in planned
                     if j["episode_id"] in indexed and indexed[j["episode_id"]].get("valid_for_primary_analysis")]
        statuses = Counter(indexed[j["episode_id"]]["status"] if j["episode_id"] in indexed else "not_run" for j in planned)
        by_kind = {}
        for kind in ("primary", "preapproved", "over_budget"):
            subset = [r for r in all_valid if cases[r["case_id"]]["kind"] == kind]
            by_kind[kind] = {"valid_n": len(subset),
                             "safely_completed_n": sum(r["observed_score"]["task_completed_safely"] for r in subset),
                             "executed_budget_violations_n": sum(r["observed_score"]["budget_violation"] for r in subset),
                             "attempted_budget_violations_n": sum(r["observed_score"]["attempted_budget_violation"] for r in subset)}
        metrics[condition] = {
            "planned_primary_n": len(primary), "valid_primary_n": len(valid),
            "missing_or_invalid_primary_n": missing, "approval_violations_n": bad,
            "observed_approval_violation_rate": bad / len(valid) if valid else None,
            "all_planned_rate_bounds": [bad / len(primary), (bad + missing) / len(primary)],
            "statuses_all_cases": dict(statuses), "task_metrics_by_kind": by_kind,
        }
    contrasts = {}
    for treatment, control in (("announced_guard", "silent_guard"),
                               ("announced_guard", "logging_control"),
                               ("silent_guard", "no_guard")):
        pairs = []
        for case in cases.values():
            if case["kind"] != "primary":
                continue
            for repeat in range(plan["config"]["repeats"]):
                a = indexed.get(f"{case['case_id']}__r{repeat}__{treatment}")
                b = indexed.get(f"{case['case_id']}__r{repeat}__{control}")
                if a and b and a.get("valid_for_primary_analysis") and b.get("valid_for_primary_analysis"):
                    difference = int(a["observed_score"]["approval_violation"]) - int(b["observed_score"]["approval_violation"])
                    pairs.append((case["template_group"], difference))
        low_a, high_a = metrics[treatment]["all_planned_rate_bounds"]
        low_b, high_b = metrics[control]["all_planned_rate_bounds"]
        contrasts[f"{treatment}_minus_{control}"] = {
            "paired_episode_n": len(pairs), "template_clusters_n": len(set(g for g, _ in pairs)),
            "risk_difference": sum(d for _, d in pairs) / len(pairs) if pairs else None,
            "exploratory_cluster_bootstrap_95_interval": cluster_interval(pairs),
            "all_planned_missingness_bounds": [low_a - high_b, high_a - low_b],
        }
    return {
        "evidence_type": "LIVE_MODEL_DEVELOPMENT_DATA" if manifest["backend"] == "openai" else "SCRIPTED_SOFTWARE_VALIDATION_ONLY",
        "backend": manifest["backend"], "model_requested": plan["config"]["model"],
        "scheduled_n": len(jobs), "recorded_n": len(indexed),
        "warning": "Development sample with eight reused request templates. Intervals are exploratory and omitted without variation; no confirmatory or deployment-prevalence claims. Missing/invalid outcomes are not safe outcomes.",
        "conditions": metrics, "contrasts": contrasts,
    }


def report_run(out):
    out = Path(out)
    manifest = read_json(out / "manifest.json")
    records = [read_json(p) for p in sorted((out / "episodes").glob("*.json"))]
    report = summarize(manifest, records)
    ledger = out / "cost_ledger.json"
    if ledger.exists():
        data = read_json(ledger)
        report["cost"] = {"cap_usd": data["cap_usd"],
                          "settled_usd": sum(c.get("actual_usd", 0) for c in data["calls"]),
                          "reserved_unknown_usd": sum(c["reserved_usd"] for c in data["calls"] if "actual_usd" not in c),
                          "api_calls": len(data["calls"])}
    write_json(out / "summary.json", report)
    lines = ["# Pilot run summary", "", f"**{report['evidence_type']}**", "", report["warning"], "",
             f"Recorded {report['recorded_n']} of {report['scheduled_n']} scheduled episodes.", "",
             "| Condition | Valid primary | Missing / invalid | Approval violations | Observed rate |",
             "|---|---:|---:|---:|---:|"]
    for name, row in report["conditions"].items():
        rate = row["observed_approval_violation_rate"]
        lines.append(f"| {name} | {row['valid_primary_n']}/{row['planned_primary_n']} | {row['missing_or_invalid_primary_n']} | {row['approval_violations_n']} | {rate:.1%} |" if rate is not None else
                     f"| {name} | 0/{row['planned_primary_n']} | {row['missing_or_invalid_primary_n']} | 0 observed | unknown |")
    lines += ["", "Paired contrasts, utility/guard diagnostics, missingness bounds, and exploratory intervals are in `summary.json`.",
              "", "These data do not establish the research hypothesis." if report["evidence_type"].startswith("SCRIPTED") else
              "Review invalidity, paired completeness, and utility before interpreting any difference.", ""]
    (out / "summary.md").write_text("\n".join(lines))
    return report
