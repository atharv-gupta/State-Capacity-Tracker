#!/usr/bin/env python3
"""Shared LLM plumbing for the federal executive-branch pipelines.

The JSON parsing, the cached-system-prompt call and the concurrent map all live
in congress_llm and are imported here rather than copied — they are generic, and
the repo already carries enough near-identical copies of its helpers.

What this module adds is the one thing that differs: the rubric composition.
congress_llm prepends rubrics/congress-adaptation.md to rubrics/rubric.md; this prepends
rubrics/federal-adaptation.md instead. Same four competencies, same relevance
scale, re-pointed at the executive branch and carrying the instrument test.
"""

import os

from tracker.congress.llm import (  # noqa: F401  (re-exported: one import per caller)
    MODEL_CLASSIFY,
    MODEL_GATE,
    RUBRIC,
    WORKERS,
    call,
    map_concurrent,
    parse_json_response,
)

from tracker.paths import RUBRICS

with open(os.path.join(RUBRICS, "federal-adaptation.md")) as f:
    ADAPTATION = f.read()

RUBRIC_SYSTEM = ADAPTATION + "\n" + RUBRIC
