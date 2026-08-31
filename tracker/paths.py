"""Repo-root-relative locations for assets the pipelines read at runtime.

Modules live in packages (tracker/congress/, tracker/federal/, ...) but the
assets they read do not — `rubrics/` and `data/` sit at the repo root, because
they are edited by humans and shouldn't be buried inside the Python tree.
Resolving them from __file__ here means a script works from any working
directory, which matters for CI and for anyone running one from their editor.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUBRICS = os.path.join(REPO_ROOT, "rubrics")
DATA = os.path.join(REPO_ROOT, "data")
