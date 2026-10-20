"""User-run PP1 decision sequence. No database work occurs on import or during preflight.

Preflight reads only aggregate herd summary CSVs. ``--run`` invokes the existing CLI
on the user's machine, in development-before-posthoc order. It never publishes an
outlook or changes a frozen configuration. Reproductive evidence is documented in
docs/pp1_plan.md; this module checks the remaining numerical exit safeguards.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys

import numpy as np
import pandas as pd

BASE_TAG = "w24_ck_kn_rk_lag90_hl6"
HORIZONS = {"monthly": (1, 3, 6, 12), "weekly": (1, 4, 8, 13)}
CLI = "components.predictive_farm_intelligence.pfoi.cli"


def exit_safeguards(base: pd.DataFrame, candidate: pd.DataFrame) -> tuple[bool, pd.DataFrame]:
    """Fixed rule: raw milking/herd improve at monthly 3/6, calvings <= +2% everywhere.

    Missing, duplicate, nonfinite or unequal-sample metric cells stop the audit. Equal
    counts are necessary, not proof of identical periods; these runs must also use the
    same default development origin schedule, as specified in the supplied run list.
    """
    required = {(g, "calvings", h) for g, hs in HORIZONS.items() for h in hs}
    required |= {("monthly", s, h) for s in ("milking", "n_herd") for h in (3, 6)}
    def cells(frame):
        cols = ["grain", "series", "horizon", "model", "mae", "n"]
        if not set(cols) <= set(frame):
            raise ValueError("summary is missing required aggregate metric columns")
        f = frame[frame["model"] == "herd_engine"].copy()
        f["horizon"] = pd.to_numeric(f["horizon"], errors="raise")
        f = f.set_index(["grain", "series", "horizon"])
        if not f.index.is_unique or not required <= set(f.index):
            raise ValueError("missing or duplicate required herd_engine summary cells")
        return f
    a, b = cells(base), cells(candidate)
    rows = []
    for key in sorted(required):
        old, new = a.loc[key], b.loc[key]
        om, nm, on, nn = map(float, (old["mae"], new["mae"], old["n"], new["n"]))
        if not np.isfinite([om, nm, on, nn]).all() or om <= 0 or nm < 0:
            raise ValueError(f"invalid metric at {key}")
        if on != nn or on < 12 or on != int(on):
            raise ValueError(f"unequal or insufficient n at {key}")
        passed = nm <= om * 1.02 if key[1] == "calvings" else nm < om
        rows.append(dict(grain=key[0], series=key[1], horizon=key[2], n=int(on),
                         baseline_mae=om, exit_mae=nm, change_pct=100 * (nm / om - 1),
                         passed=passed))
    table = pd.DataFrame(rows)
    return bool(table["passed"].all()), table


def evaluation_commands(exit_kept: bool, folder: Path, jobs: int) -> list[list[str]]:
    """No fast-half-life, final test, build-outlook, --force or --write in this sequence."""
    flags = ["--preset", "pfoi-1.1", "--out", str(folder)]
    if exit_kept:
        flags += ["--exit-model", "lactation"]
    milk = flags + ["--k", "anchor_first"]
    tag = BASE_TAG + ("_xl" if exit_kept else "")
    mtag = "herd_fitted_p1_g0_kf_" + tag
    def command(name, opts):
        return [sys.executable, "-m", CLI, name, *opts]
    return [
        command("backtest-milk", [*milk, "--grain", "both", "--jobs", str(jobs)]),
        command("milk-report", milk),
        command("break-reset", ["--herd-tag", tag, "--milk-tag", mtag, "--out", str(folder)]),
        command("scorecard", [*milk, "--block", "development", "--intervals", "empirical"]),
        command("scorecard", [*milk, "--block", "development", "--intervals", "aci"]),
        command("scorecard", [*milk, "--block", "development", "--intervals", "aci", "--interval-quality", "off"]),
        command("backtest-herd", [*flags, "--grain", "both", "--block", "posthoc", "--jobs", str(jobs)]),
        command("backtest-milk", [*milk, "--grain", "both", "--block", "posthoc", "--jobs", str(jobs)]),
        command("milk-report", [*milk, "--block", "posthoc"]),
        command("break-reset", ["--herd-tag", tag, "--milk-tag", mtag, "--block", "posthoc",
                                "--out", str(folder)]),
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("logs/pfoi"))
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--run", action="store_true", help="run the printed evaluation commands on your machine")
    args = p.parse_args(argv)
    try:
        frames = []
        for tag in (BASE_TAG, BASE_TAG + "_xl"):
            frames.append(pd.concat([pd.read_csv(args.out / f"herd_backtest_summary_{g}_{tag}.csv")
                                     for g in HORIZONS], ignore_index=True))
        keep, audit = exit_safeguards(*frames)
    except (OSError, ValueError, KeyError) as err:
        print(f"Exit decision INCOMPLETE: {err}. No evaluation commands were run.", file=sys.stderr)
        return 2
    print("Exit-only safeguards (DEVELOPMENT; n is scored forecast periods):", flush=True)
    print(audit.round(4).to_string(index=False), flush=True)
    print("Exit option: " + ("KEEP (numerical safeguards passed; reproductive evidence in PP1 plan)"
                             if keep else "DROP (fixed numerical safeguards failed; use reference engine)"),
          flush=True)
    commands = evaluation_commands(keep, args.out, args.jobs)
    for cmd in commands:
        print("\n" + shlex.join(cmd), flush=True)
        if args.run:
            subprocess.run(cmd, check=True)
            if cmd[3] == "backtest-milk" and "--block" not in cmd:
                tag = "herd_fitted_p1_g0_kf_" + BASE_TAG + ("_xl" if keep else "")
                for grain in HORIZONS:
                    path = args.out / f"milk_backtest_errors_{grain}_{tag}.csv"
                    try:
                        e = pd.read_csv(path)
                    except (OSError, ValueError) as err:
                        raise RuntimeError("Development milk errors missing; posthoc stopped") from err
                    if e.empty or "model" not in e or not (e["model"] == "milk_baseline").any():
                        raise RuntimeError("Development milk errors incomplete; posthoc stopped")
            if cmd[3] == "break-reset" and "--block" not in cmd:
                from .break_eval import verdict
                tag = "herd_fitted_p1_g0_kf_" + BASE_TAG + ("_xl" if keep else "")
                t = pd.read_csv(args.out / f"break_reset_comparison_{tag}.csv")
                reset, reasons = verdict(t)
                print("SELECTED-CONFIG RESET: " + ("KEEP" if reset else "DROP"), flush=True)
                for reason in reasons:
                    print(reason, flush=True)
                if (t["n_after"] < 12).any():
                    print("Small after-break samples: numerical verdict is not strong confirmation.", flush=True)
    print("\nIntervals remain unconfirmed until matched coverage AND width are reviewed. "
          "No outlook was published. Posthoc scores are post-test development.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
