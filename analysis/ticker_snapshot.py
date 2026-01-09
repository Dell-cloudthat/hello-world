#!/usr/bin/env python3
"""
Return a JSON snapshot for an individual ticker for the local dashboard.

Metrics:
- latest price
- 3m/6m/12m total return (daily close approximation)
- max drawdown over last 3y and last 1y
- correlation + beta vs S&P 500 (using weekly returns over ~3y)

Also returns series for charting (last ~1y of prices normalized to 100).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class Config:
    start: str = "2015-01-01"
    chart_days: int = 252  # ~1y
    beta_years: int = 3


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
    return px.dropna(how="all")


def _max_drawdown(levels: pd.Series) -> float:
    levels = levels.dropna()
    if len(levels) < 2:
        return float("nan")
    peak = levels.cummax()
    dd = levels / peak - 1.0
    return float(dd.min())


def _total_return(levels: pd.Series, days: int) -> float:
    levels = levels.dropna()
    if len(levels) <= days:
        return float("nan")
    return float(levels.iloc[-1] / levels.iloc[-1 - days] - 1.0)


def _beta_and_corr(asset: pd.Series, bench: pd.Series) -> tuple[float, float]:
    # Weekly returns to reduce micro-noise.
    a = asset.dropna().resample("W-FRI").last().pct_change(fill_method=None)
    b = bench.dropna().resample("W-FRI").last().pct_change(fill_method=None)
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(j) < 20:
        return float("nan"), float("nan")
    corr = float(j["a"].corr(j["b"]))
    var = float(j["b"].var(ddof=1))
    if var <= 0:
        beta = float("nan")
    else:
        beta = float(j["a"].cov(j["b"]) / var)
    return beta, corr


def snapshot(ticker: str, cfg: Config) -> dict[str, Any]:
    px = _download_close([ticker, "^GSPC"], start=cfg.start)
    if ticker not in px.columns or px[ticker].dropna().empty:
        raise RuntimeError(f"No data returned for ticker: {ticker}")
    if "^GSPC" not in px.columns or px["^GSPC"].dropna().empty:
        raise RuntimeError("No S&P 500 data returned.")

    t_px = px[ticker].dropna()
    spx = px["^GSPC"].reindex(t_px.index).ffill().dropna()
    t_px = t_px.reindex(spx.index).dropna()

    asof = t_px.index[-1]
    last = float(t_px.iloc[-1])

    r3m = _total_return(t_px, 63)
    r6m = _total_return(t_px, 126)
    r12m = _total_return(t_px, 252)

    # Drawdowns over last 1y and 3y (approx)
    t_1y = t_px.iloc[-min(len(t_px), 252) :]
    t_3y = t_px.iloc[-min(len(t_px), 252 * 3) :]
    dd_1y = _max_drawdown(t_1y)
    dd_3y = _max_drawdown(t_3y)

    beta, corr = _beta_and_corr(t_3y, spx.reindex(t_3y.index))

    # Chart series (normalized to 100 at start)
    chart = t_px.iloc[-min(len(t_px), cfg.chart_days) :].copy()
    base = float(chart.iloc[0])
    norm = (chart / base) * 100.0 if base != 0 else chart * np.nan

    return {
        "ticker": ticker,
        "as_of": asof.strftime("%Y-%m-%d"),
        "price": {"last": last},
        "returns": {"r_3m": r3m, "r_6m": r6m, "r_12m": r12m},
        "risk": {"max_drawdown_1y": dd_1y, "max_drawdown_3y": dd_3y},
        "market": {"beta_3y_weekly": beta, "corr_3y_weekly": corr},
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in norm.index],
            "norm_100": [float(x) for x in norm.to_numpy()],
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--start", default="2015-01-01")
    args = ap.parse_args()

    t = args.ticker.strip().upper()
    cfg = Config(start=args.start)
    print(json.dumps(snapshot(t, cfg), indent=2))


if __name__ == "__main__":
    main()

