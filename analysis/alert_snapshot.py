#!/usr/bin/env python3
"""
Emit a JSON snapshot for the local alert dashboard.

Computes:
- S&P 500 current drawdown from peak (since start)
- VIX current level
- Trigger state (buy window) based on drawdown bands + VIX filter
- Candidate list (reads analysis/out/top25_candidates.csv if present, else falls back)

This is research tooling, not investment advice.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import yfinance as yf


@dataclass(frozen=True)
class TriggerPolicy:
    start: str = "2006-01-01"
    lookback_days: int = 252
    vix_min: float = 25.0
    # drawdown bands (<=) -> recommended % of target allocation to deploy
    bands: tuple[tuple[float, int], ...] = (
        (-0.25, 100),
        (-0.20, 85),
        (-0.15, 60),
        (-0.10, 25),
    )


DEFAULT_ETF_PROXIES = ["KSA", "UAE", "QAT", "INDA", "EIDO", "EWW", "EWZ", "ECH", "EPU", "VNM"]


def _download_close(tickers: list[str], start: str) -> pd.DataFrame:
    df = yf.download(
        tickers=tickers,
        start=start,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(df.columns, pd.MultiIndex):
        px = df["Close"].copy()
    else:
        px = df.rename("Close").to_frame()
        px.columns = tickers
    px = px.dropna(how="all")
    # Normalize index to ISO strings later
    return px


def _drawdown(levels: pd.Series) -> pd.Series:
    levels = levels.dropna()
    peak = levels.cummax()
    return levels / peak - 1.0


def _load_candidates(repo_root: Path) -> list[dict[str, Any]]:
    """
    Returns a list of candidates to show when triggers fire.
    Prefers the locally-generated Top 25 list (FinanceDatabase metadata + proxy scoring).
    """
    path = repo_root / "analysis" / "out" / "top25_candidates.csv"
    if path.exists():
        df = pd.read_csv(path)
        # Expect first column is "ticker" if written with index=True; but csv writer used index=True
        # which writes an unnamed first column. Handle both.
        if "ticker" in df.columns:
            tickers = df["ticker"].astype(str).tolist()
            name_col = "name" if "name" in df.columns else None
            country_col = "country" if "country" in df.columns else None
        else:
            tickers = df.iloc[:, 0].astype(str).tolist()
            name_col = "name" if "name" in df.columns else None
            country_col = "country" if "country" in df.columns else None

        out: list[dict[str, Any]] = []
        for i, t in enumerate(tickers[:25]):
            row = df.iloc[i]
            out.append(
                {
                    "ticker": t,
                    "name": (str(row[name_col]) if name_col else None),
                    "country": (str(row[country_col]) if country_col else None),
                }
            )
        return out

    return [{"ticker": t, "name": None, "country": None} for t in DEFAULT_ETF_PROXIES]


def snapshot(policy: TriggerPolicy) -> dict[str, Any]:
    repo_root = Path(os.getcwd()).resolve()

    px = _download_close(["^GSPC", "^VIX"], start=policy.start)
    if "^GSPC" not in px.columns or px["^GSPC"].dropna().empty:
        raise RuntimeError("No S&P 500 data returned from Yahoo Finance.")
    if "^VIX" not in px.columns or px["^VIX"].dropna().empty:
        raise RuntimeError("No VIX data returned from Yahoo Finance.")

    spx = px["^GSPC"].dropna()
    vix = px["^VIX"].reindex(spx.index).ffill().dropna()
    dd = _drawdown(spx)

    asof = spx.index[-1]
    spx_now = float(spx.iloc[-1])
    peak_now = float(spx.cummax().iloc[-1])
    dd_now = float(dd.iloc[-1])
    vix_now = float(vix.loc[asof])

    # Determine trigger status
    vix_ok = vix_now >= policy.vix_min
    allocation = 0
    band_hit = None
    for thr, pct in policy.bands:
        if dd_now <= thr and vix_ok:
            allocation = pct
            band_hit = thr
            break

    status = "WAIT"
    if allocation > 0:
        status = "BUY_WINDOW"
    elif dd_now <= -0.10 and not vix_ok:
        status = "WATCH_VIX"

    # Next threshold guidance
    bands_sorted = sorted([thr for thr, _ in policy.bands], reverse=True)  # -0.10, -0.15...
    next_thr = None
    for thr in bands_sorted:
        if dd_now > thr:
            next_thr = thr
            break

    candidates = _load_candidates(repo_root)

    # Series for charts (last N days)
    tail = slice(max(0, len(spx) - policy.lookback_days), len(spx))
    idx = spx.index[tail]
    spx_s = spx.iloc[tail]
    dd_s = dd.reindex(idx)
    vix_s = vix.reindex(idx)

    return {
        "as_of": asof.strftime("%Y-%m-%d"),
        "spx": {"level": spx_now, "peak": peak_now, "drawdown": dd_now},
        "vix": {"level": vix_now, "min_required": policy.vix_min, "ok": vix_ok},
        "signal": {
            "status": status,
            "band_hit": band_hit,
            "recommended_allocation_pct_of_target": allocation,
            "next_drawdown_trigger": next_thr,
        },
        "candidates": candidates,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in idx],
            "spx": [float(x) for x in spx_s.to_numpy()],
            "drawdown": [float(x) for x in dd_s.to_numpy()],
            "vix": [float(x) for x in vix_s.to_numpy()],
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    policy = TriggerPolicy()
    print(json.dumps(snapshot(policy), indent=2))


if __name__ == "__main__":
    main()

