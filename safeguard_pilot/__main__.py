import argparse
import json
import os
from pathlib import Path

from .analysis import report_run
from .api import ProviderError
from .common import read_json, write_json
from .design import make_plan, prompts
from .runner import execute, manifest_for


def main():
    parser = argparse.ArgumentParser(description="Safeguard awareness development pilot. Local mock tools only.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "preflight", "run", "smoke"):
        p = sub.add_parser(command)
        p.add_argument("--config", default="configs/dev.json")
        if command != "preflight":
            p.add_argument("--out", required=True)
        if command in ("run", "smoke"):
            p.add_argument("--resume", action="store_true")
            p.add_argument("--budget-usd", type=float, default=5.0)
        if command == "smoke":
            p.add_argument("--policy", choices=("compliant", "always_purchase"), default="compliant")
    p = sub.add_parser("analyze")
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        if args.command == "analyze":
            report = report_run(args.out)
        else:
            config = read_json(args.config)
            plan = make_plan(config)
            if args.command == "preflight":
                ready = bool(os.environ.get("OPENAI_API_KEY"))
                print(json.dumps({"credential_configured": ready, "model": config["model"],
                                  "cases": len(plan["cases"]), "episodes": len(plan["schedule"]),
                                  "maximum_api_calls": len(plan["schedule"]) * config["max_turns"],
                                  "network_checked": False, "api_calls_made": 0}, indent=2))
                return 0 if ready else 2
            if args.command == "plan":
                out = Path(args.out)
                if out.exists() and any(out.iterdir()):
                    raise ValueError("Plan directory is nonempty; choose a new path")
                out.mkdir(parents=True, exist_ok=True)
                write_json(out / "plan.json", manifest_for(config, "plan-only", 5.0))
                write_json(out / "cases.json", plan["cases"])
                cases = {c["case_id"]: c for c in plan["cases"]}
                with (out / "prompts.jsonl").open("w") as handle:
                    for job in plan["schedule"]:
                        handle.write(json.dumps({**job, "input": prompts(cases[job["case_id"]], job["condition"])}, ensure_ascii=False) + "\n")
                print(f"Prepared {len(plan['cases'])} development cases and {len(plan['schedule'])} episodes. No API calls made.")
                return 0
            backend = "openai" if args.command == "run" else "scripted:" + args.policy
            execute(config, args.out, backend=backend, budget=args.budget_usd, resume=args.resume)
            report = report_run(args.out)
        print(json.dumps({"evidence_type": report["evidence_type"], "recorded_n": report["recorded_n"],
                          "scheduled_n": report["scheduled_n"], "summary": str(Path(args.out) / "summary.md")}, indent=2))
        failures = any(any(status not in ("purchased", "stopped") for status in row["statuses_all_cases"])
                       for row in report["conditions"].values())
        return 2 if failures else 0
    except (ValueError, KeyError, OSError, ProviderError) as error:
        parser.exit(2, f"ERROR: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
