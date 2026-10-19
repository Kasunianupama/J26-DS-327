"""Score backtest origins serially or in a process pool (same results, same order).

Origins are independent once their inputs are loaded. Each worker process builds its
own context once (``make_ctx(*ctx_args)``, which opens its own read-only source) and
then scores a contiguous block of origins, so origins in the same month share any
per-process cache. ``make_ctx`` and ``score`` must be module-level functions.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from typing import Callable

_CTX = None
_SCORE = None


def _init_worker(make_ctx, ctx_args, score):
    global _CTX, _SCORE
    _CTX, _SCORE = make_ctx(*ctx_args), score


def _score_block(block):
    return [(i, _SCORE(_CTX, o)) for i, o in block]


def _blocks(origins: list[date], n: int) -> list[list[tuple[int, date]]]:
    items = list(enumerate(origins))
    size = max(1, -(-len(items) // n))
    return [items[i:i + size] for i in range(0, len(items), size)]


def map_origins(origins: list[date], score: Callable, make_ctx: Callable, ctx_args: tuple,
                jobs: int = 1, progress: Callable[[int, int, date], None] | None = None,
                serial_ctx=None) -> list:
    """``[score(ctx, origin) for origin in origins]``, in that order.

    ``serial_ctx`` (when given) is used for ``jobs <= 1`` instead of building one.
    """
    n = len(origins)
    if jobs <= 1:
        ctx = serial_ctx if serial_ctx is not None else make_ctx(*ctx_args)
        out = []
        for i, origin in enumerate(origins):
            if progress:
                progress(i, n, origin)
            out.append(score(ctx, origin))
        return out
    # one BLAS thread per process, so N processes do not fight over the cores
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(var, "1")
    results: dict[int, object] = {}
    with ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn"),
                             initializer=_init_worker,
                             initargs=(make_ctx, ctx_args, score)) as pool:
        futures = [pool.submit(_score_block, b) for b in _blocks(origins, jobs * 4)]
        for fut in as_completed(futures):
            for i, res in fut.result():
                if progress:
                    progress(len(results), n, origins[i])
                results[i] = res
    return [results[i] for i in range(n)]


def resolve_jobs(jobs: int) -> int:
    """CLI value: N > 0 as given, 0 = CPU cores - 1 (at least 1)."""
    return jobs if jobs > 0 else max(1, (os.cpu_count() or 2) - 1)
