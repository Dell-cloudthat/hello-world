"""
Universe builder using FinanceDatabase (JerBouma/FinanceDatabase).

This module is intentionally small and explicit:
- FinanceDatabase provides *metadata* (country, exchange, market cap, sector, etc.)
- We use it to generate a candidate list (tickers) for downstream price/regime analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

try:
    import financedatabase as fd
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Missing dependency financedatabase. Install with: python3 -m pip install financedatabase"
    ) from e


@dataclass(frozen=True)
class EquityUniverseSpec:
    countries: list[str]
    top_n_per_country: int = 50
    min_market_cap: float | None = None
    exchanges: list[str] | None = None
    sectors: list[str] | None = None
    industries: list[str] | None = None


def build_equities_universe(spec: EquityUniverseSpec) -> pd.DataFrame:
    """
    Returns a DataFrame indexed by ticker symbol with metadata columns.

    The returned tickers are FinanceDatabase symbols (often Yahoo-style with exchange suffixes).
    """
    data = fd.Equities().data.copy()

    # Normalize inputs
    countries = [c.strip() for c in spec.countries if str(c).strip()]
    if not countries:
        raise ValueError("spec.countries must be non-empty")

    df = data[data["country"].isin(countries)].copy()

    if spec.exchanges:
        exchanges = [x.strip() for x in spec.exchanges if str(x).strip()]
        df = df[df["exchange"].isin(exchanges)].copy()

    if spec.sectors:
        sectors = [x.strip() for x in spec.sectors if str(x).strip()]
        df = df[df["sector"].isin(sectors)].copy()

    if spec.industries:
        industries = [x.strip() for x in spec.industries if str(x).strip()]
        df = df[df["industry"].isin(industries)].copy()

    if spec.min_market_cap is not None:
        # Some entries are missing or non-numeric; coerce and drop.
        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
        df = df[df["market_cap"] >= float(spec.min_market_cap)].copy()

    # Rank within each country by market cap if available, else keep arbitrary ordering.
    if "market_cap" in df.columns:
        df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
        # If market cap is missing for a country, still return something:
        # rank NaNs as very small rather than excluding them.
        mc_for_rank = df["market_cap"].fillna(-1)
        df["_mc_rank"] = mc_for_rank.groupby(df["country"]).rank(
            ascending=False, method="first"
        )
        df = df[df["_mc_rank"] <= int(spec.top_n_per_country)].copy()
        df = df.drop(columns=["_mc_rank"])
    else:
        # Fallback: take first N per country
        df = df.groupby("country").head(int(spec.top_n_per_country)).copy()

    # Keep a consistent column order for downstream use
    keep_cols = [
        "name",
        "currency",
        "sector",
        "industry_group",
        "industry",
        "exchange",
        "market",
        "country",
        "market_cap",
        "isin",
        "cusip",
        "figi",
        "composite_figi",
        "shareclass_figi",
        "website",
        "summary",
    ]
    cols = [c for c in keep_cols if c in df.columns]
    df = df[cols].copy()

    # Ensure the index is named as ticker
    df.index = df.index.astype(str)
    df.index.name = "ticker"

    return df.sort_values(["country", "market_cap"], ascending=[True, False], na_position="last")


def available_countries() -> list[str]:
    data = fd.Equities().data
    return sorted(set(data["country"].dropna().astype(str).tolist()))

