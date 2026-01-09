#!/usr/bin/env python3
"""
Timing study: when to rotate into international proxies during US drawdowns.

This script uses liquid Yahoo Finance proxies:
- US market: ^GSPC (S&P 500) and ^VIX (volatility)
- International proxies: a user-provided ticker list (defaults in this script)

It reports forward returns after drawdown triggers, optionally conditioned on VIX.

Not investment advice. Research tooling only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class TimingConfig:
    start: str = "2006-01-01"
    end: str | None = None
    interval: str = "1d"
    # drawdown triggers (peak-to-trough) on S&P 500
    drawdowns: tuple[float, ...] = (-0.05, -0.10, -0.15, -0.20, -0.25, -0.30)
    # forward windows in trading days (~63=3m, 126=6m, 252=12m)
    fwds: tuple[int, ...] = (63, 126, 252)


DEFAULT_INTL = [
    # MENA + Asia + LatAm liquid country ETF proxies
    "KSA",
    "UAE",
    "QAT",
    "INDA",
    "EIDO",
    "EWW",
    "EWZ",
    "ECH",
    "EPU",
    "VNM",
]


def download_adj_close(tickers: list[str], start: str, end: str | None, interval: str) -> pd.DataFrame:
    data = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(data.columns, pd.MultiIndex):
        px = data["Close"].copy()
    else:
        px = data.rename("Close").to_frame()
        px.columns = tickers
    px = px.dropna(how="all")
    return px


def compute_drawdown(levels: pd.Series) -> pd.Series:
    levels = levels.dropna()
    peak = levels.cummax()
    return levels / peak - 1.0


def first_crossing_dates(dd: pd.Series, threshold: float, cooldown_days: int = 63) -> list[pd.Timestamp]:
    """
    Find dates where drawdown first crosses below threshold, with cooldown
    to avoid multiple triggers within same episode.
    """
    dd = dd.dropna()
    hits = dd <= threshold
    dates: list[pd.Timestamp] = []
    last = None
    for ts, hit in hits.items():
        if not hit:
            continue
        if last is None:
            dates.append(ts)
            last = ts
            continue
        if (ts - last).days >= cooldown_days:
            dates.append(ts)
            last = ts
    return dates


def forward_return(px: pd.Series, entry_dates: list[pd.Timestamp], fwd_days: int) -> pd.Series:
    px = px.dropna()
    rets = {}
    for d in entry_dates:
        if d not in px.index:
            # align to next available trading day
            idx = px.index.searchsorted(d)
            if idx >= len(px.index):
                continue
            d0 = px.index[idx]
        else:
            d0 = d
        i0 = px.index.get_loc(d0)
        i1 = i0 + fwd_days
        if i1 >= len(px.index):
            continue
        d1 = px.index[i1]
        rets[d0] = float(px.loc[d1] / px.loc[d0] - 1.0)
    return pd.Series(rets).sort_index()


def summarize(series: pd.Series) -> dict[str, float]:
    s = series.dropna()
    if s.empty:
        return {"n": 0.0, "mean": np.nan, "median": np.nan, "win_rate": np.nan}
    return {
        "n": float(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "win_rate": float((s > 0).mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2006-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--intl", nargs="*", default=DEFAULT_INTL)
    ap.add_argument("--cooldown-days", type=int, default=63)
    ap.add_argument("--vix-min", type=float, default=None, help="Only take triggers when VIX >= this")
    ap.add_argument("--out", default="analysis/out/timing_summary.csv")
    args = ap.parse_args()

    cfg = TimingConfig(start=args.start, end=args.end)

    tickers = ["^GSPC", "^VIX"] + list(dict.fromkeys([t.upper() for t in args.intl if t.strip()]))
    px = download_adj_close(tickers, start=cfg.start, end=cfg.end, interval=cfg.interval)

    spx = px["^GSPC"].dropna()
    vix = px["^VIX"].dropna()
    dd = compute_drawdown(spx).rename("spx_drawdown")

    # Align VIX to SPX calendar (forward-fill for missing days)
    vix_a = vix.reindex(spx.index).ffill()

    rows = []
    for thr in cfg.drawdowns:
        entry_dates = first_crossing_dates(dd, thr, cooldown_days=args.cooldown_days)
        if args.vix_min is not None:
            entry_dates = [d for d in entry_dates if float(vix_a.loc[d]) >= float(args.vix_min)]

        # Bench: SPX forward returns
        for fwd in cfg.fwds:
            spx_f = forward_return(spx, entry_dates, fwd)
            spx_sum = summarize(spx_f)

            for t in [c for c in px.columns if c not in ("^GSPC", "^VIX")]:
                r = forward_return(px[t], entry_dates, fwd)
                s = summarize(r)
                # Outperformance rate on same entry dates
                j = pd.concat([r.rename("intl"), spx_f.rename("spx")], axis=1).dropna()
                outperf = float((j["intl"] > j["spx"]).mean()) if not j.empty else np.nan

                rows.append(
                    {
                        "drawdown_trigger": thr,
                        "vix_min": args.vix_min,
                        "fwd_days": fwd,
                        "ticker": t,
                        "n": s["n"],
                        "mean": s["mean"],
                        "median": s["median"],
                        "win_rate": s["win_rate"],
                        "outperf_rate_vs_spx": outperf,
                        "spx_mean": spx_sum["mean"],
                        "spx_median": spx_sum["median"],
                        "spx_win_rate": spx_sum["win_rate"],
                    }
                )

    out = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)

    # Also print a compact "best by trigger" view for 12m horizon
    view = out[out["fwd_days"] == 252].copy()
    view = view.sort_values(["drawdown_trigger", "mean"], ascending=[True, False])
    best = view.groupby(["drawdown_trigger"]).head(5)
    print(best[["drawdown_trigger", "vix_min", "ticker", "n", "mean", "outperf_rate_vs_spx"]].to_string(index=False))


if __name__ == "__main__":
    main()

