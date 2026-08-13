#!/usr/bin/env python3
"""Shared LLM plumbing for the congressional pipelines.

Loads the rubric once (adaptation prefix + rubric.md), and holds the JSON
parsing and concurrent-classify helpers that congress_api_sync.py and
congress_dedupe.py both need.
"""

import concurrent.futures
import json
import os

MODEL_GATE = "claude-haiku-4-5"
MODEL_CLASSIFY = "claude-sonnet-4-6"
WORKERS = 6

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, "congress_rubric_adaptation.md")) as f:
    ADAPTATION = f.read()
with open(os.path.join(_HERE, "rubric.md")) as f:
    RUBRIC = f.read()

# The adaptation re-points the four competencies at the federal government and
# adds the Congress-only carve-outs; rubric.md supplies the definitions and the
# relevance scale. Same composition pattern as candidates_dedupe.py.
RUBRIC_SYSTEM = ADAPTATION + "\n" + RUBRIC


def parse_json_response(text):
    """Take the first complete JSON object in the response.

    The naive first-`{`-to-last-`}` slice used elsewhere in this repo breaks
    when the model emits two objects back to back: the slice spans both and
    json.loads raises "Extra data". raw_decode stops at the first complete
    object instead.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in response: {text[:120]!r}")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


def call(client, model, system, payload, max_tokens=900):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user",
                   "content": payload if isinstance(payload, str) else json.dumps(payload)}],
    )
    return parse_json_response(resp.content[0].text)


def map_concurrent(fn, items, workers=WORKERS, label="item"):
    """Run fn over items concurrently, preserving order. A failure yields None
    so one bad item can't sink the batch."""
    results = [None] * len(items)
    if not items:
        return results

    def one(i):
        try:
            return i, fn(items[i])
        except Exception as e:
            print(f"  {label} error [{i}]: {e}")
            return i, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, out in ex.map(one, range(len(items))):
            results[i] = out
    return results
