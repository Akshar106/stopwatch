"""Ask Stopwatch eval harness (docs/05 §6).

Scores the first tool call against the labeled expectation, checks grounding, and checks that out-of-scope
questions get no tool calls and no numbers. Every live run costs money, so it stops at --max-cost.

    cd backend
    uv run python ../evals/ask/run_evals.py --dry                 # validate the question file only
    uv run python ../evals/ask/run_evals.py --max-cost 0.50       # live run against SITE_URL's published data

Requires an Anthropic credential (ANTHROPIC_API_KEY or an `ant auth login` profile) and a published build.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TOOLS = {"find_stop", "route_summary", "stop_reliability"}


def load() -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines() if line.strip()]
    for r in rows:
        exp = r["expect"]
        assert r["question"].strip(), r["id"]
        assert exp.get("out_of_scope") or exp.get("tool") in TOOLS, f"{r['id']}: bad expectation {exp}"
    return rows


class RecordingClient:
    """Wraps the real client to capture the first tool call of each question."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.first_tool: dict[str, Any] | None = None
        self.beta = self
        self.messages = self

    def create(self, **kwargs: Any) -> Any:
        resp = self.inner.beta.messages.create(**kwargs)
        if self.first_tool is None:
            for b in resp.content:
                if b.type == "tool_use":
                    self.first_tool = {"name": b.name, "input": dict(b.input)}
                    break
        return resp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-cost", type=float, default=0.50, help="stop once this many USD have been spent")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    rows = load()
    if args.dry:
        print(f"{len(rows)} questions OK")
        return 0

    import anthropic

    from stopwatch.ask.service import ask_with_client
    from stopwatch.ask.tools import PublishedData
    from stopwatch.platform.blobstore import open_blobstore
    from stopwatch.platform.config import get_settings

    s = get_settings()
    model = args.model or s.ask_model
    data = PublishedData(open_blobstore(s.site_url), agency_id=s.agency_ids[0])
    client = anthropic.Anthropic()
    budget = int(args.max_cost * 1_000_000)
    spent = 0
    results = []
    for r in rows:
        if spent >= budget:
            print(f"stopping: spent ${spent / 1e6:.3f} of ${args.max_cost:.2f}")
            break
        rec = RecordingClient(client)
        resp, usage = ask_with_client(rec, model, r["question"], data, budget - spent)
        spent += usage.cost_microusd()
        exp = r["expect"]
        if exp.get("out_of_scope"):
            ok_tool = rec.first_tool is None
            ok_args = True
        else:
            ok_tool = rec.first_tool is not None and rec.first_tool["name"] == exp["tool"]
            got = (rec.first_tool or {}).get("input", {})
            ok_args = ok_tool and all(str(got.get(k, "")).lower() == str(v).lower() for k, v in exp["args"].items())
        grounded = resp.reason != "ungrounded"
        results.append({"id": r["id"], "tool_ok": ok_tool, "args_ok": ok_args, "grounded": grounded,
                        "fallback": resp.fallback, "reason": resp.reason, "first_tool": rec.first_tool})
        print(f"{r['id']}: tool={'✓' if ok_tool else '✗'} args={'✓' if ok_args else '✗'} "
              f"grounded={'✓' if grounded else '✗'}")
    n = len(results) or 1
    summary = {
        "model": model, "questions": len(results), "cost_usd": round(spent / 1e6, 4),
        "tool_accuracy": round(sum(x["tool_ok"] for x in results) / n, 3),
        "arg_accuracy": round(sum(x["args_ok"] for x in results) / n, 3),
        "grounding_rate": round(sum(x["grounded"] for x in results) / n, 3),
        "targets": {"tool_accuracy": 0.9, "grounding_rate": 1.0},
    }
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps({"summary": summary, "results": results},
                                                                           indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if summary["tool_accuracy"] >= 0.9 and summary["grounding_rate"] >= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
