"""Responses API adapter with persistent conservative accounting. Standard library only."""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .common import canonical, read_json, write_json


class BudgetExceeded(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


class Ledger:
    """Reserve before every request, retain reservations for unknown-cost failures.

    This is a client-side safeguard, not a provider-enforced billing limit.
    A conservative byte-based input bound includes 4096 tokens of overhead.
    An unexpectedly larger bill stops the run rather than silently continuing.
    """
    def __init__(self, path, cap, config):
        self.path = Path(path)
        self.config = config
        if not 0 < cap <= 75:
            raise ValueError("Budget must be greater than zero and at most $75")
        if self.path.exists():
            self.data = read_json(self.path)
            if self.data["cap_usd"] != cap:
                raise ValueError("Resume must use the original budget cap")
        else:
            self.data = {"cap_usd": cap, "calls": []}
            write_json(self.path, self.data)

    def total(self):
        return sum(c.get("actual_usd", c["reserved_usd"]) for c in self.data["calls"])

    def reserve(self, payload, episode_id, turn):
        bound = len(canonical(payload).encode("utf-8")) + 4096
        maximum = (bound * self.config["input_usd_per_million"] +
                   payload["max_output_tokens"] * self.config["output_usd_per_million"]) / 1_000_000
        if self.total() + maximum > self.data["cap_usd"]:
            raise BudgetExceeded("Next request would exceed the conservative budget reservation")
        call_id = len(self.data["calls"])
        self.data["calls"].append({"call_id": call_id, "episode_id": episode_id, "turn": turn,
                                   "reserved_usd": maximum, "state": "reserved",
                                   "input_token_bound": bound, "started_at": time.time()})
        write_json(self.path, self.data)
        return call_id

    def settle(self, call_id, response):
        if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
            raise ProviderError("API response missing valid usage; request reservation retained")
        usage = response["usage"]
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        if type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
            raise ProviderError("API response missing valid usage; request reservation retained")
        cost = (input_tokens * self.config["input_usd_per_million"] +
                output_tokens * self.config["output_usd_per_million"]) / 1_000_000
        entry = self.data["calls"][call_id]
        entry.update({"state": "settled", "actual_usd": cost, "usage": usage,
                      "response_id": response.get("id"), "resolved_model": response.get("model")})
        write_json(self.path, self.data)
        if cost > entry["reserved_usd"] + 1e-9:
            raise ProviderError("Actual cost exceeded conservative reservation; stop and inspect pricing/token bounds")


class OpenAIProvider:
    def __init__(self, config, ledger, raw_directory):
        self.key = os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise ProviderError("OPENAI_API_KEY is not configured. No API calls made. Configure it locally; do not paste it into chat.")
        self.config, self.ledger = config, ledger
        self.raw_directory = Path(raw_directory)

    def respond(self, inputs, tools, episode_id, turn, context=None):
        payload = {
            "model": self.config["model"], "input": inputs, "tools": tools,
            "store": False, "parallel_tool_calls": False, "tool_choice": "auto",
            "max_output_tokens": self.config["max_output_tokens"],
            "temperature": self.config["temperature"],
        }
        call_id = self.ledger.reserve(payload, episode_id, turn)
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses", data=canonical(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config["request_timeout_seconds"]) as handle:
                response = json.load(handle)
        except urllib.error.HTTPError as error:
            raise ProviderError(f"OpenAI HTTP {error.code}; no automatic retry; reservation retained") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ProviderError("Network/response error; no automatic retry; reservation retained") from None
        write_json(self.raw_directory / f"call-{call_id:06d}.json", response)
        self.ledger.settle(call_id, response)
        return response


class ScriptedProvider:
    """Condition-blind deterministic test double, never empirical model evidence."""
    def __init__(self, policy):
        if policy not in ("compliant", "always_purchase"):
            raise ValueError("Unknown scripted policy")
        self.policy = policy

    def respond(self, inputs, tools, episode_id, turn, context=None):
        case, env = context
        item_id = case.get("item_id")
        if "items" in case:
            action = None
            attempted = {e["arguments"]["item_id"] for e in env.events if e["tool"] == "purchase"}
            for item in case["items"]:
                item_id = item["item_id"]
                if self.policy == "always_purchase":
                    if item_id not in attempted:
                        action = "purchase"
                        break
                elif item_id not in env.purchased_ids and env.spent_cents + item["price_cents"] <= case["budget_cents"]:
                    if env.approved[item_id]:
                        action = "purchase"
                        break
                    if item_id not in env.approval_requested_ids:
                        action = "request_approval"
                        break
        elif self.policy == "always_purchase":
            # Attempt one purchase regardless of approval, then stop if blocked.
            action = "purchase" if not env.events else None
        elif case["price_cents"] > case["budget_cents"]:
            action = None
        elif env.approved:
            action = "purchase"
        elif not env.approval_requested:
            action = "request_approval"
        else:
            action = None
        if action:
            output = [{"type": "function_call", "call_id": f"scripted-{turn}", "name": action,
                       "arguments": json.dumps({"item_id": item_id}), "status": "completed"}]
        else:
            output = [{"type": "message", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "I cannot proceed with this order."}]}]
        return {"id": f"SCRIPTED-{episode_id}-{turn}", "model": "SCRIPTED-NOT-A-LANGUAGE-MODEL",
                "status": "completed", "output": output,
                "usage": {"input_tokens": 0, "output_tokens": 0}}
