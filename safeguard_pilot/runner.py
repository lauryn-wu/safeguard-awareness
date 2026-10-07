"""Episode execution, immutable manifests, explicit failures and resumable runs."""

import json
import os
import time
from pathlib import Path

from .api import BudgetExceeded, Ledger, OpenAIProvider, ProviderError, ScriptedProvider
from .common import canonical, digest, read_json, write_json
from .design import TOOLS, make_plan, prompts
from .environment import ShoppingEnvironment
from .multi_item import MultiItemEnvironment


VALID_STATUSES = ("purchased", "stopped")


def source_fingerprint():
    root = Path(__file__).parent
    sources = {p.name: p.read_text() for p in sorted(root.glob("*.py"))}
    for protocol in sorted(root.parent.glob("PROTOCOL*.md")):
        sources[protocol.name] = protocol.read_text()
    return digest(sources)


def manifest_for(config, backend, budget):
    plan = make_plan(config)
    immutable = {"plan": plan, "backend": backend, "budget_usd": budget,
                 "source_sha256": source_fingerprint()}
    return {**immutable, "fingerprint": digest(immutable)}


def parse_response(response):
    if not isinstance(response, dict):
        return None, "invalid_response"
    if response.get("status") != "completed":
        return None, "incomplete_response"
    output = response.get("output")
    if not isinstance(output, list) or not output:
        return None, "invalid_response"
    calls = [o for o in output if isinstance(o, dict) and o.get("type") == "function_call"]
    if len(calls) > 1:
        # Never impose a made-up order on simultaneous approval and purchase calls.
        return None, "parallel_calls_rejected"
    unsupported = [o for o in output if not isinstance(o, dict) or o.get("type") not in ("function_call", "message", "reasoning")]
    if unsupported:
        return None, "invalid_response"
    if any(o.get("status") not in (None, "completed") for o in output):
        return None, "incomplete_response"
    if calls:
        call = calls[0]
        if not isinstance(call.get("call_id"), str) or not call["call_id"] or not isinstance(call.get("name"), str) or not call["name"]:
            return None, "invalid_tool_call"
        try:
            arguments = json.loads(call["arguments"])
        except (KeyError, ValueError, TypeError):
            return None, "invalid_tool_call"
        return (call, arguments), None
    messages = [o for o in output if o.get("type") == "message"]
    if any(not isinstance(o.get("content"), list) for o in messages):
        return None, "invalid_response"
    text_exists = any(
        isinstance(c, dict) and c.get("type") in ("output_text", "refusal") and
        isinstance(c.get("text") or c.get("refusal"), str) and bool((c.get("text") or c.get("refusal")).strip())
        for o in messages for c in o["content"]
    )
    return (None, None) if text_exists else (None, "invalid_response")


def run_episode(case, job, config, provider, checkpoint=lambda record: None):
    environment = MultiItemEnvironment if "items" in case else ShoppingEnvironment
    env = environment(case, guard_enabled=job["condition"] != "no_guard")
    inputs = prompts(case, job["condition"])
    record = {**job, "kind": case["kind"], "template_group": case["template_group"],
              "model": config["model"], "initial_input": inputs.copy(), "calls": [],
              "events": [], "status": "running", "started_at": time.time()}
    stop_batch = False
    for turn in range(config["max_turns"]):
        checkpoint(record)
        try:
            response = provider.respond(inputs, TOOLS, job["episode_id"], turn, context=(case, env))
        except BudgetExceeded as error:
            record.update(status="budget_exhausted", error=str(error))
            stop_batch = True
            break
        except ProviderError as error:
            record.update(status="provider_error", error=str(error))
            stop_batch = True
            break
        record["calls"].append(response)
        parsed, error = parse_response(response)
        if error:
            record.update(status=error)
            break
        if parsed is None:
            record["status"] = "stopped"
            break
        call, arguments = parsed
        try:
            result = env.step(call["name"], arguments)
        except ValueError as error:
            record.update(status="invalid_tool_call", error=str(error))
            break
        record["events"] = list(env.events)
        if (env.terminal if "items" in case else env.purchased):
            record["status"] = "purchased"
            break
        # Carry the entire returned output, including reasoning items, forward.
        inputs.extend(response["output"])
        inputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": canonical(result)})
        checkpoint(record)
    else:
        record["status"] = "turn_limit"
    record["valid_for_primary_analysis"] = record["status"] in VALID_STATUSES
    record["observed_score"] = env.score()
    if not record["valid_for_primary_analysis"]:
        record["observed_score"]["task_completed_safely"] = False
    record["finished_at"] = time.time()
    return record, stop_batch


def execute(config, out, backend="openai", budget=5.0, resume=False):
    if backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise ProviderError("OPENAI_API_KEY is not configured. No API calls made. Configure it locally; do not paste it into chat.")
    if backend not in ("openai", "scripted:compliant", "scripted:always_purchase"):
        raise ValueError("Unknown backend")
    if not 0 < budget <= 75:
        raise ValueError("Budget must be greater than zero and at most $75")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".run.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Run is locked; ensure no runner is active before removing a stale .run.lock") from None
    with os.fdopen(fd, "w") as handle:
        handle.write(str(os.getpid()))
    try:
        manifest = manifest_for(config, backend, budget)
        path = out / "manifest.json"
        if path.exists():
            if not resume:
                raise ValueError("Run already exists; use --resume or choose a new directory")
            if read_json(path)["fingerprint"] != manifest["fingerprint"]:
                raise ValueError("Configuration, prompts, code, protocol, backend, or budget changed; choose a new run directory")
        else:
            write_json(path, {**manifest, "created_at": time.time()})
        episodes = out / "episodes"
        episodes.mkdir(exist_ok=True)
        inflight = out / "inflight.json"
        if inflight.exists():
            interrupted = read_json(inflight)
            terminal = episodes / (interrupted["episode_id"] + ".json")
            if not terminal.exists():
                interrupted.update(status="interrupted", valid_for_primary_analysis=False,
                                   error="Previous process stopped; no automatic rerun of this episode",
                                   finished_at=time.time())
                write_json(terminal, interrupted)
            inflight.unlink()
        ledger = Ledger(out / "cost_ledger.json", budget, config) if backend == "openai" else None
        provider = OpenAIProvider(config, ledger, out / "raw_responses") if ledger else ScriptedProvider(backend.split(":")[1])
        cases = {c["case_id"]: c for c in manifest["plan"]["cases"]}
        for job in manifest["plan"]["schedule"]:
            destination = episodes / (job["episode_id"] + ".json")
            if destination.exists():
                previous = read_json(destination)
                if previous["prompt_sha256"] != job["prompt_sha256"] or previous["fingerprint"] != manifest["fingerprint"]:
                    raise ValueError("Existing episode does not match the run manifest")
                continue
            def checkpoint(record):
                write_json(inflight, {**record, "fingerprint": manifest["fingerprint"], "backend": backend})
            record, stop = run_episode(cases[job["case_id"]], job, config, provider, checkpoint)
            record.update(fingerprint=manifest["fingerprint"], backend=backend)
            write_json(destination, record)
            inflight.unlink(missing_ok=True)
            print(f"{job['episode_id']}: {record['status']}", flush=True)
            if stop:
                break
        return manifest
    finally:
        lock.unlink(missing_ok=True)
