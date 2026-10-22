"""Per-forecast-date charts of the 1.3 hybrid against pfoi-1.2.0-dev, same layout as compare-runs.

Needs (a) the 1.2-dev page documents from build-outlook (logs/pfoi/outlook/pfoi-1.2.0-dev/run_YYYYMM.json,
which also supply the recorded history and outcomes) and (b) paths.csv from pfoi.hybrid_runner.
Herd-level aggregates only. Writes PNGs to logs/pfoi/compare/ and prints the matched-period scores.

    .venv/bin/python components/predictive_farm_intelligence/docs/make_hybrid_compare.py \
        logs/pfoi_hybrid_1_3_dev_v1 2017-01-01 2019-06-01 2020-08-01 2022-09-01 2023-11-01
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, so the package imports
from components.predictive_farm_intelligence.pfoi.compare_runs import plot, score

SERIES = {"herd_milk": "milk_litres", "milking": "milking", "n_herd": "total_herd",
          "calvings": "calvings", "real_abortions": "abortions"}
GRAINS = {"monthly": "month", "weekly": "week", "daily": "day"}
BASE = "pfoi-1.2.0-dev"
LABEL = "pfoi-1.3-hybrid"


def hybrid_doc(base_doc, paths, origin, grain):
    p = paths[(paths.origin == pd.Timestamp(origin)) & paths.series.isin(SERIES) & paths.grain.isin(GRAINS)]
    rows = [dict(series=SERIES[r.series], grain=GRAINS[r.grain], horizon=int(r.horizon),
                 target_period=pd.Timestamp(r.period_start).date().isoformat(),
                 forecast=r.forecast, lower=r.lower, upper=r.upper) for r in p.itertuples()]
    # recorded history and outcomes are the same facts for both models: take them from the 1.2 document
    return dict(base_doc, outlook=rows, model_version=LABEL, corrections=[])


def main(run_dir, origins, grain="monthly", logs="logs/pfoi"):
    paths = pd.read_csv(Path(run_dir)/"paths.csv", parse_dates=["origin", "period_start"])
    dest = Path(logs)/"compare"
    dest.mkdir(parents=True, exist_ok=True)
    tables = []
    for o in origins:
        origin = date.fromisoformat(o)
        doc_path = Path(logs)/"outlook"/BASE/f"run_{origin:%Y%m}.json"
        if not doc_path.exists():
            print(f"{origin}: missing {doc_path} (run build-outlook for {BASE} first)")
            continue
        if not (paths.origin == pd.Timestamp(origin)).any():
            print(f"{origin}: not in this run's paths.csv (development replay ends 2023-12)")
            continue
        base_doc = json.loads(doc_path.read_text())
        cand = hybrid_doc(base_doc, paths, origin, grain)
        g = GRAINS[grain]
        plot(base_doc, cand, origin, dest/f"compare_{g}_{origin:%Y%m}_{BASE}_vs_{LABEL}.png",
             labels=(BASE, LABEL), grain=g)
        tables.append(score(base_doc, cand, grain=g).assign(origin=f"{origin:%Y-%m}"))
    if tables:
        t = pd.concat(tables, ignore_index=True).set_index(["origin", "series"])
        pd.set_option("display.width", 200)
        print("MAE/bias = forecast - recorded; change_pct < 0 = 1.3 better\n", t.round(2).to_string())
        print(f"\nCharts in {dest}/")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
