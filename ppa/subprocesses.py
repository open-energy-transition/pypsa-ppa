"""Helpers for running solves in spawned child processes.

Children are started with spawn, never fork: linopy builds models with polars,
whose thread pool is not fork-safe. Once the app process has solved anything
in-process (serial multi-year path, single-day reference run), a forked child
deadlocks on its first polars query. A fresh interpreter costs ~3 s of imports.
"""
from __future__ import annotations

import contextlib
import multiprocessing
import sys
import types


def spawn_context():
    return multiprocessing.get_context("spawn")


@contextlib.contextmanager
def main_module_hidden():
    """Keep spawned children from re-importing `__main__`.

    Under Streamlit, `__main__` is the app script itself, so spawn would re-run
    the whole app in each child. With a bare placeholder (no `__file__`/
    `__spec__`) a child imports only what unpickling its target needs. Wrap
    every call that starts a process (`Process.start`, or the submits of a
    spawn-context `ProcessPoolExecutor`, which launch workers synchronously).
    """
    main = sys.modules.get("__main__")
    sys.modules["__main__"] = types.ModuleType("__main__")
    try:
        yield
    finally:
        sys.modules["__main__"] = main
