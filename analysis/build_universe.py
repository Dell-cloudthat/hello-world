#!/usr/bin/env python3
"""
Build a candidate ticker universe from FinanceDatabase and emit a regime-screen config.

Example:
python3 analysis/build_universe.py \
  --countries "Saudi Arabia" "Qatar" "United Arab Emirates" "India" "Indonesia" "Mexico" "Brazil" "Chile" "Peru" \
  --top-n-per-country 40 \
  --min-market-cap 5000000000 \
  --out-config analysis/config.generated.json \
  --out-meta analysis/universe_meta.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from universe_financedb import EquityUniverseSpec, build_equities_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", required=True)
    ap.add_argument("--top-n-per-country", type=int, default=50)
    ap.add_argument("--min-market-cap", type=float, default=None)
    ap.add_argument("--exchange", action="append", default=None, help="Repeatable exchange filter")
    ap.add_argument("--sector", action="append", default=None, help="Repeatable sector filter")
    ap.add_argument("--industry", action="append", default=None, help="Repeatable industry filter")

    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--top-n", type=int, default=25, help="Top N shown in rankings.md")

    ap.add_argument("--out-config", type=Path, required=True)
    ap.add_argument("--out-meta", type=Path, required=True)
    args = ap.parse_args()

    spec = EquityUniverseSpec(
        countries=args.countries,
        top_n_per_country=args.top_n_per_country,
        min_market_cap=args.min_market_cap,
        exchanges=args.exchange,
        sectors=args.sector,
        industries=args.industry,
    )
    universe = build_equities_universe(spec)
    args.out_meta.parent.mkdir(parents=True, exist_ok=True)
    universe.to_csv(args.out_meta, index=True)

    tickers = universe.index.tolist()

    cfg = {
        "start": args.start,
        "end": args.end,
        "top_n": args.top_n,
        "tickers": tickers,
        "weights": {
            "us_down_mean": 0.4,
            "us_down_outperf_rate": 0.25,
            "overall_cagr": 0.15,
            "drawdown_penalty": 0.2,
            "qualitative": 0.0,
        },
        "qualitative": {},
        "universe_meta_csv": str(args.out_meta),
    }

    args.out_config.parent.mkdir(parents=True, exist_ok=True)
    args.out_config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    print(f"Wrote {len(tickers)} tickers to {args.out_config}")
    print(f"Wrote metadata to {args.out_meta}")


if __name__ == "__main__":
    main()

