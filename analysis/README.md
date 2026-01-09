# International “US downtrend” winner screen (research tooling)

This folder contains a **regime-based screening script** that ranks a set of *international proxies* (typically **country ETFs**) by how they historically performed **during US drawdowns**, and optionally blends in your qualitative “geopolitical/fragmentation” criteria as manual scores.

## What data this uses from the linked “DB”

The link you provided (`datasets/commons/.../stock-market-data.md`) is a **catalog**. The concrete datasets it points to that are useful here are:

- `core/s-and-p-500`: long-run S&P 500 monthly levels (used to define “US downtrend”)
- `core/finance-vix`: VIX daily closes (used to define “risk-off”)
- `core/oil-prices`: Brent daily prices (used to define “energy up”)
- `core/gold-prices`: gold monthly prices (optional macro context)

**Notably missing from that catalog** (so not computable directly from it):

- Foreign capital flows / index inclusion events (EPFR, MSCI, FTSE rebalances, privatization calendars)
- Foreign ownership / US retail ownership
- Options coverage / open interest by market
- State-aligned balance sheet share (SOE weights), pricing support, policy backstops

Because of that, this tool separates:

- **Quant screen**: “who historically held up when the US was down”
- **Qual overlay**: your geopolitical/fragmentation thesis as manual (0–1) scores per ticker

## Quick start

1) Ensure the DataHub CSVs exist at repo root (already downloaded in this workspace):

- `sp500.csv`
- `vix.csv`
- `brent.csv`
- `gold.csv`

2) Run the screen (downloads proxy prices via Yahoo Finance):

```bash
python3 analysis/regime_screen.py \
  --config analysis/config.example.json \
  --outdir analysis/out
```

Outputs:

- `analysis/out/regimes_monthly.csv`: regime calendar with US-down / risk-off / energy-up flags
- `analysis/out/candidates_monthly_returns.csv`: monthly returns for your tickers
- `analysis/out/rankings.csv`: metrics + score per ticker
- `analysis/out/rankings.md`: top-N table

## New: build a universe from `JerBouma/FinanceDatabase`

If you don’t want to hand-maintain tickers, you can generate a universe from **FinanceDatabase** (equity metadata including `country`, `exchange`, `sector`, `industry`, `market_cap`, etc.).

Note: the current implementation supports **FinanceDatabase equities** (not ETFs) because the ETF table in the package doesn’t consistently include country-level fields.

### Option A: generate a ticker list + config file

```bash
python3 analysis/build_universe.py \
  --countries "Saudi Arabia" "Qatar" "United Arab Emirates" "India" "Indonesia" "Mexico" "Brazil" "Chile" "Peru" \
  --top-n-per-country 40 \
  --min-market-cap 5000000000 \
  --out-config analysis/config.generated.json \
  --out-meta analysis/universe_meta.csv

python3 analysis/regime_screen.py \
  --config analysis/config.generated.json \
  --outdir analysis/out
```

### Option B: generate inside `regime_screen.py` via config `"universe"`

Instead of `"tickers": [...]`, your config can include:

```json
{
  "start": "2006-01-01",
  "end": null,
  "top_n": 25,
  "universe": {
    "source": "financedatabase",
    "type": "equities",
    "countries": ["Saudi Arabia", "Qatar", "United Arab Emirates", "India", "Indonesia", "Mexico", "Brazil", "Chile", "Peru"],
    "top_n_per_country": 40,
    "min_market_cap": 5000000000
  }
}
```

When you run the screen, it will write `analysis/out/universe_meta.csv` with the tickers and metadata it selected.

## How to adapt to your criteria

### Capital Flow Inversion (proxy ideas)

- Add external series: **portfolio flows** (EPFR), **IMF CPIS** holdings, **BIS** banking flows
- Event flags: MSCI/FTSE **index inclusion**, privatization announcements, reforms

### Low Western Narrative Penetration / Sparse options coverage (proxy ideas)

- US-listed ETF AUM / turnover as a rough proxy for US retail accessibility
- Options: OCC / exchange-level open interest, number of listed options series

### Beneficiaries of fragmentation (proxy ideas)

- Oil/gas export exposure (Brent-linked upside)
- Food/materials security: fertilizer, grains, metals export share
- Infrastructure localization: construction/materials weights + fiscal spend indicators

This script currently treats these as **manual scores** in `config.example.json` because the linked catalog doesn’t contain those fields.

## Important note

This is **not** a forecast and not investment advice. It’s a reproducible way to test your thesis against history, then layer on additional datasets for the non-price constraints you care about.

