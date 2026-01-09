#!/usr/bin/env python3
"""
Regime-based screen for "who wins when the US is down".

IMPORTANT LIMITATION:
The referenced datasets/commons "stock-market-data.md" catalog does not include
international country index levels, capital flows, ownership, or options coverage.
So this script:
  1) Uses DataHub "core/*" datasets to define US/risk regimes (S&P 500, VIX, oil, gold)
  2) Uses optional market proxies (e.g., country ETFs) via Yahoo Finance to estimate
     how candidates behaved historically during US drawdowns.
  3) Allows manual qualitative scoring for the criteria you listed (flows, state alignment,
     narrative penetration, fragmentation beneficiaries, etc.).

This is research tooling, not investment advice.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency yfinance. Install with: python3 -m pip install yfinance"
    ) from e


@dataclass(frozen=True)
class RegimeConfig:
    us_down_lookback_months: int = 6
    us_down_threshold: float = -0.05  # 6m total return <= -5%
    risk_off_vix_threshold: float = 25.0  # monthly average VIX >= 25
    energy_up_threshold: float = 0.10  # 6m total return >= +10% (Brent)


def _parse_date_any(s: str) -> pd.Timestamp:
    # Supports "YYYY-MM-DD" and "MM/DD/YYYY" and "YYYY-MM"
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m"):
        try:
            return pd.Timestamp(datetime.strptime(s, fmt).date())
        except ValueError:
            pass
    # last resort: pandas parser
    return pd.to_datetime(s, errors="coerce")


def _read_series_csv(path: Path, date_col: str, value_col: str) -> pd.Series:
    df = pd.read_csv(path)
    df[date_col] = df[date_col].map(_parse_date_any)
    df = df.dropna(subset=[date_col, value_col]).sort_values(date_col)
    s = pd.Series(df[value_col].astype(float).to_numpy(), index=df[date_col].to_numpy())
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")]
    return s


def _to_month_end_level(s: pd.Series) -> pd.Series:
    s = s.sort_index()
    # Pandas deprecates "M" in favor of "ME" (month-end).
    return s.resample("ME").last().dropna()


def _to_monthly_avg(s: pd.Series) -> pd.Series:
    s = s.sort_index()
    return s.resample("ME").mean().dropna()


def _total_return(levels: pd.Series, months: int) -> pd.Series:
    # total return over N months using month-end levels
    return levels / levels.shift(months) - 1.0


def _max_drawdown(levels: pd.Series) -> float:
    levels = levels.dropna()
    if len(levels) < 2:
        return float("nan")
    peak = levels.cummax()
    dd = levels / peak - 1.0
    return float(dd.min())


def _annualized_return(monthly_returns: pd.Series) -> float:
    r = monthly_returns.dropna()
    if r.empty:
        return float("nan")
    growth = float((1.0 + r).prod())
    years = len(r) / 12.0
    if years <= 0:
        return float("nan")
    return growth ** (1.0 / years) - 1.0


def _annualized_vol(monthly_returns: pd.Series) -> float:
    r = monthly_returns.dropna()
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * math.sqrt(12.0))


def _download_yf_monthly_levels(
    tickers: list[str],
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    # Use auto_adjust=True to approximate total-return-ish series for ETFs.
    # Note: This is still not a true total return index for many markets.
    data = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        group_by="column",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    # yfinance shapes differ for 1 ticker vs many tickers
    if isinstance(data.columns, pd.MultiIndex):
        # Prefer "Close" after auto_adjust; Adj Close may be missing.
        close = data["Close"].copy()
    else:
        close = data.rename("Close").to_frame()

    close = close.dropna(how="all")
    monthly = close.resample("ME").last().dropna(how="all")
    # Ensure columns are tickers
    if monthly.shape[1] == 1 and tickers and monthly.columns[0] == "Close":
        monthly.columns = [tickers[0]]
    return monthly


def _load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return cfg


def _resolve_tickers(cfg: dict[str, Any], outdir: Path) -> tuple[list[str], Path | None]:
    """
    Returns (tickers, universe_meta_csv_path_or_None).

    Config supports either:
    - explicit "tickers": [...]
    - or a generated universe:
        "universe": {
          "source": "financedatabase",
          "type": "equities",
          "countries": [...],
          "top_n_per_country": 50,
          "min_market_cap": 5000000000,
          "exchanges": ["..."],
          "sectors": ["..."],
          "industries": ["..."]
        }
    """
    if "tickers" in cfg and isinstance(cfg["tickers"], list) and cfg["tickers"]:
        tickers = [str(t).strip().upper() for t in cfg["tickers"] if str(t).strip()]
        return tickers, None

    uni = cfg.get("universe")
    if not isinstance(uni, dict):
        raise ValueError("Config must include either non-empty 'tickers' or a 'universe' object")

    source = str(uni.get("source", "")).strip().lower()
    utype = str(uni.get("type", "")).strip().lower()
    if source != "financedatabase":
        raise ValueError(f"Unsupported universe source: {source!r}")
    if utype != "equities":
        raise ValueError(f"Unsupported universe type: {utype!r} (only 'equities' supported)")

    # Import only when needed (keeps base script usable without financedatabase)
    from universe_financedb import EquityUniverseSpec, build_equities_universe

    countries = uni.get("countries", [])
    if not isinstance(countries, list) or not countries:
        raise ValueError("Universe must include non-empty list: universe.countries")

    spec = EquityUniverseSpec(
        countries=[str(c) for c in countries],
        top_n_per_country=int(uni.get("top_n_per_country", 50)),
        min_market_cap=(
            None
            if uni.get("min_market_cap", None) is None
            else float(uni.get("min_market_cap"))
        ),
        exchanges=uni.get("exchanges", None),
        sectors=uni.get("sectors", None),
        industries=uni.get("industries", None),
    )
    meta = build_equities_universe(spec)
    meta_path = outdir / "universe_meta.csv"
    meta.to_csv(meta_path, index=True)
    tickers = [str(t).strip().upper() for t in meta.index.tolist()]
    return tickers, meta_path


def run(
    *,
    cfg_path: Path,
    outdir: Path,
    sp500_csv: Path,
    vix_csv: Path,
    brent_csv: Path,
    gold_csv: Path,
    regime_cfg: RegimeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = _load_config(cfg_path)
    outdir.mkdir(parents=True, exist_ok=True)
    tickers, universe_meta_path = _resolve_tickers(cfg, outdir)

    if universe_meta_path is not None:
        cfg["universe_meta_csv"] = str(universe_meta_path)

    # --- Regime definitions from DataHub core datasets ---
    spx = _read_series_csv(sp500_csv, date_col="Date", value_col="SP500")
    spx_m = _to_month_end_level(spx)
    spx_r = spx_m.pct_change().rename("SPX_ret")

    vix = _read_series_csv(vix_csv, date_col="DATE", value_col="CLOSE")
    vix_m = _to_monthly_avg(vix).rename("VIX_avg")

    brent = _read_series_csv(brent_csv, date_col="Date", value_col="Price")
    brent_m = _to_month_end_level(brent)
    brent_6m = _total_return(brent_m, regime_cfg.us_down_lookback_months).rename("Brent_6m")

    gold = _read_series_csv(gold_csv, date_col="Date", value_col="Price")
    gold_m = _to_month_end_level(gold).rename("Gold")

    spx_6m = _total_return(spx_m, regime_cfg.us_down_lookback_months).rename("SPX_6m")

    regimes = (
        pd.concat([spx_m.rename("SPX"), spx_r, spx_6m, vix_m, brent_6m, gold_m], axis=1)
        .dropna(subset=["SPX"])
        .sort_index()
    )
    regimes["US_down"] = regimes["SPX_6m"] <= regime_cfg.us_down_threshold
    regimes["Risk_off"] = regimes["VIX_avg"] >= regime_cfg.risk_off_vix_threshold
    regimes["Energy_up"] = regimes["Brent_6m"] >= regime_cfg.energy_up_threshold

    # --- Candidate proxies (optional external prices via Yahoo Finance) ---
    start = cfg.get("start", None)
    end = cfg.get("end", None)

    px_m = _download_yf_monthly_levels(tickers=tickers, start=start, end=end)
    px_m = px_m.sort_index()
    r_m = px_m.pct_change(fill_method=None)

    # Align to regime calendar
    common_idx = regimes.index.intersection(r_m.index)
    regimes_a = regimes.loc[common_idx].copy()
    r_a = r_m.loc[common_idx].copy()

    # --- Metrics ---
    qual = cfg.get("qualitative", {}) or {}
    min_history_months = int(cfg.get("min_history_months", 36))
    max_abs_monthly_ret = float(cfg.get("max_abs_monthly_ret", 2.0))
    weights = cfg.get(
        "weights",
        {
            "us_down_mean": 0.40,
            "us_down_outperf_rate": 0.25,
            "overall_cagr": 0.15,
            "drawdown_penalty": 0.20,
            "qualitative": 0.0,
        },
    )

    us_down_mask = regimes_a["US_down"].fillna(False)
    if us_down_mask.sum() < 6:
        # Still compute, but warn in output.
        regimes_a.attrs["warning"] = (
            f"Only {int(us_down_mask.sum())} US-down months found on the aligned calendar. "
            "Consider lowering thresholds or expanding history."
        )

    rows: list[dict[str, Any]] = []
    for t in tickers:
        tr = r_a[t].dropna()
        if tr.empty or tr.shape[0] < min_history_months:
            continue
        # Basic data quality guardrail (Yahoo can contain bad series / splits / stubs)
        if (tr.abs() > max_abs_monthly_ret).any():
            continue
        levels = px_m[t].dropna()

        overall_cagr = _annualized_return(tr)
        overall_vol = _annualized_vol(tr)
        mdd = _max_drawdown(levels)

        down_r = r_a.loc[us_down_mask, t].dropna()
        down_mean = float(down_r.mean()) if not down_r.empty else float("nan")

        # Outperform rate vs S&P monthly returns in US-down months
        spx_down = regimes_a.loc[us_down_mask, "SPX_ret"].dropna()
        joined = pd.concat([down_r.rename("t"), spx_down.rename("spx")], axis=1).dropna()
        outperf_rate = float((joined["t"] > joined["spx"]).mean()) if not joined.empty else float("nan")

        # Optional qualitative scoring in [0,1]
        q = qual.get(t, {})
        if isinstance(q, dict):
            q_score = float(np.mean([float(v) for v in q.values()])) if q else float("nan")
        else:
            q_score = float("nan")

        # Score: higher is better (simple linear blend)
        score = 0.0
        score += weights.get("us_down_mean", 0.0) * (0.0 if math.isnan(down_mean) else down_mean)
        score += weights.get("us_down_outperf_rate", 0.0) * (
            0.0 if math.isnan(outperf_rate) else outperf_rate
        )
        score += weights.get("overall_cagr", 0.0) * (0.0 if math.isnan(overall_cagr) else overall_cagr)
        # Drawdown penalty: more negative drawdown => subtract more
        score -= weights.get("drawdown_penalty", 0.0) * (0.0 if math.isnan(mdd) else abs(mdd))
        score += weights.get("qualitative", 0.0) * (0.0 if math.isnan(q_score) else q_score)

        rows.append(
            {
                "ticker": t,
                "overall_cagr": overall_cagr,
                "overall_vol": overall_vol,
                "max_drawdown": mdd,
                "us_down_months": int(down_r.shape[0]),
                "us_down_mean_monthly_ret": down_mean,
                "us_down_outperf_rate": outperf_rate,
                "qual_score_0_1": q_score,
                "score": score,
            }
        )

    results = pd.DataFrame(rows).sort_values("score", ascending=False)

    # --- Write outputs ---
    regimes_a.to_csv(outdir / "regimes_monthly.csv", index=True)
    r_a.to_csv(outdir / "candidates_monthly_returns.csv", index=True)
    results.to_csv(outdir / "rankings.csv", index=False)

    # Small markdown summary
    top_n = int(cfg.get("top_n", 15))
    md_path = outdir / "rankings.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Regime screen rankings (research, not advice)\n\n")
        if "warning" in regimes_a.attrs:
            f.write(f"**Warning:** {regimes_a.attrs['warning']}\n\n")
        f.write("## Top candidates\n\n")
        f.write(results.head(top_n).to_markdown(index=False))
        f.write("\n")

    return regimes_a, results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path, help="Path to config JSON")
    ap.add_argument("--outdir", default=Path("analysis/out"), type=Path)
    ap.add_argument("--sp500", default=Path("sp500.csv"), type=Path)
    ap.add_argument("--vix", default=Path("vix.csv"), type=Path)
    ap.add_argument("--brent", default=Path("brent.csv"), type=Path)
    ap.add_argument("--gold", default=Path("gold.csv"), type=Path)
    ap.add_argument("--us-down-lookback", type=int, default=6)
    ap.add_argument("--us-down-threshold", type=float, default=-0.05)
    ap.add_argument("--risk-off-vix", type=float, default=25.0)
    ap.add_argument("--energy-up-threshold", type=float, default=0.10)
    args = ap.parse_args()

    regime_cfg = RegimeConfig(
        us_down_lookback_months=args.us_down_lookback,
        us_down_threshold=args.us_down_threshold,
        risk_off_vix_threshold=args.risk_off_vix,
        energy_up_threshold=args.energy_up_threshold,
    )

    run(
        cfg_path=args.config,
        outdir=args.outdir,
        sp500_csv=args.sp500,
        vix_csv=args.vix,
        brent_csv=args.brent,
        gold_csv=args.gold,
        regime_cfg=regime_cfg,
    )


if __name__ == "__main__":
    main()

