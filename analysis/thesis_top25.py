#!/usr/bin/env python3
"""
Create a 'top 25' candidate list from FinanceDatabase metadata, using heuristic proxies
for the user's criteria (capital flow inversion, state-aligned balance sheets, low Western
narrative penetration, fragmentation beneficiaries).

Limitations:
- FinanceDatabase does NOT provide flows, foreign ownership, or options coverage.
- This script approximates those criteria using *proxies* (country, sector, listing venue).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from universe_financedb import EquityUniverseSpec, build_equities_universe


COUNTRY_BASE = {
    # "Saudi + select Asia / LatAm shine" => highest base weights here
    "Saudi Arabia": 1.00,
    "United Arab Emirates": 0.90,
    "Qatar": 0.90,
    "Indonesia": 0.75,
    "India": 0.70,
    "Mexico": 0.75,
    "Brazil": 0.75,
    "Chile": 0.70,
    "Peru": 0.70,
}

SECTOR_FRAGMENTATION = {
    # Beneficiaries of fragmentation: energy nationalism, materials security, infra localization
    "Energy": 1.00,
    "Materials": 0.90,
    "Industrials": 0.80,
    "Utilities": 0.75,
    "Consumer Staples": 0.70,  # food security-ish
    "Financials": 0.65,  # state-aligned credit channel proxy
    "Real Estate": 0.45,
    "Communication Services": 0.35,
    "Consumer Discretionary": 0.30,
    "Health Care": 0.25,
    "Information Technology": 0.20,
}

# Local listing suffixes by country (Yahoo-style). Used as proxy for lower "Western narrative"
# and lower US retail/options adjacency.
LOCAL_SUFFIX = {
    "Saudi Arabia": [".SR"],
    "Qatar": [".QA"],
    "United Arab Emirates": [".DU", ".AD"],
    "Indonesia": [".JK"],
    "India": [".NS", ".BO"],
    "Mexico": [".MX"],
    "Brazil": [".SA"],
    "Chile": [".SN"],
    "Peru": [".LM"],
}

# A coarse list of "more Western / cross-listed" venues to penalize.
WESTERN_EXCHANGE_CODES = {
    # US
    "NYQ",
    "NMS",
    "NGM",
    "ASE",
    "BATS",
    # UK/Europe cross-list venues often used in the DB
    "LSE",
    "FRA",
    "MUN",
    "STU",
    "BER",
    "DUS",
    "HAM",
    "XETRA",
    "MIL",
    "PAR",
    "AMS",
}


def _is_local_listing(ticker: str, country: str) -> bool:
    ticker = str(ticker).upper()
    for suf in LOCAL_SUFFIX.get(country, []):
        if ticker.endswith(suf):
            return True
    return False


def score_row(row: pd.Series) -> float:
    country = str(row.get("country", "")).strip()
    sector = str(row.get("sector", "")).strip()
    exchange = str(row.get("exchange", "")).strip()
    ticker = str(row.name)

    c = COUNTRY_BASE.get(country, 0.50)
    s = SECTOR_FRAGMENTATION.get(sector, 0.40)

    # Listing proxy:
    # - reward local listing
    # - penalize obvious Western cross-listing venues
    local_bonus = 0.15 if _is_local_listing(ticker, country) else 0.0
    western_penalty = 0.15 if exchange in WESTERN_EXCHANGE_CODES else 0.0

    # Market cap proxy: favor larger/central domestic players (dominance + state capacity adjacency).
    mc = row.get("market_cap", np.nan)
    try:
        mc = float(mc) if mc == mc else np.nan
    except Exception:
        mc = np.nan
    # soft log-scale: ~0.0 (unknown) .. ~0.25 (mega)
    if mc is np.nan or not np.isfinite(mc) or mc <= 0:
        mc_bonus = 0.0
    else:
        mc_bonus = float(np.clip(np.log10(mc) - 9.0, 0.0, 3.0) / 12.0)  # 1B..1T -> 0..0.25

    # Blend (bounded-ish in [0, ~1.4])
    return 0.55 * c + 0.35 * s + local_bonus + mc_bonus - western_penalty


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=list(COUNTRY_BASE.keys()))
    ap.add_argument("--top-n-per-country", type=int, default=250)
    ap.add_argument("--min-market-cap", type=float, default=None)
    ap.add_argument("--max-per-country", type=int, default=6, help="Diversification cap")
    ap.add_argument("--out-csv", type=Path, default=Path("analysis/out/top25_candidates.csv"))
    ap.add_argument("--out-md", type=Path, default=Path("analysis/out/top25_candidates.md"))
    args = ap.parse_args()

    spec = EquityUniverseSpec(
        countries=args.countries,
        top_n_per_country=args.top_n_per_country,
        min_market_cap=args.min_market_cap,
    )
    uni = build_equities_universe(spec)
    if uni.empty:
        raise SystemExit("Universe is empty (try removing --min-market-cap or increasing coverage).")

    uni = uni.copy()
    uni["thesis_score"] = uni.apply(score_row, axis=1)
    uni["is_local_listing_proxy"] = [
        _is_local_listing(t, c) for t, c in zip(uni.index.tolist(), uni["country"].tolist())
    ]
    # Sort by thesis score then market cap
    uni["market_cap_num"] = pd.to_numeric(uni.get("market_cap", np.nan), errors="coerce")
    ranked = uni.sort_values(["thesis_score", "market_cap_num"], ascending=[False, False])

    # De-duplicate share classes / cross-listings by (country, name) keeping best-ranked row.
    # (FinanceDatabase often includes multiple listings for the same company.)
    ranked["_dedupe_key"] = (
        ranked["country"].astype(str).str.strip()
        + "|"
        + ranked["name"].astype(str).str.strip().str.lower()
    )
    ranked = ranked.drop_duplicates(subset=["_dedupe_key"], keep="first").drop(columns=["_dedupe_key"])

    # Diversified selection: avoid a single-country sweep.
    picks: list[str] = []
    per_country: dict[str, int] = {}
    for t, row in ranked.iterrows():
        c = str(row.get("country", "")).strip()
        if not c:
            continue
        if per_country.get(c, 0) >= int(args.max_per_country):
            continue
        picks.append(t)
        per_country[c] = per_country.get(c, 0) + 1
        if len(picks) >= 25:
            break

    top25 = ranked.loc[picks].copy()
    cols = [
        "name",
        "country",
        "sector",
        "industry",
        "exchange",
        "currency",
        "market_cap_num",
        "is_local_listing_proxy",
        "thesis_score",
    ]
    cols = [c for c in cols if c in top25.columns]
    out = top25[cols].copy()
    out = out.rename(columns={"market_cap_num": "market_cap"})

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=True)

    # Markdown table for quick viewing
    args.out_md.write_text(
        "# Top 25 candidates (FinanceDatabase metadata + proxy scoring)\n\n"
        "These are *metadata/proxy* matches for the requested criteria. Criteria that require\n"
        "flows/ownership/options data are **not** directly measured here.\n\n"
        + out.to_markdown(index=True),
        encoding="utf-8",
    )

    print(f"Wrote: {args.out_csv}")
    print(f"Wrote: {args.out_md}")


if __name__ == "__main__":
    main()

