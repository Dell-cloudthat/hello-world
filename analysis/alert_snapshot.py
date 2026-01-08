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
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from email.message import EmailMessage

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

@dataclass(frozen=True)
class EmailConfig:
    """
    SMTP config via environment variables:

    - ALERT_SMTP_HOST
    - ALERT_SMTP_PORT (default 587)
    - ALERT_SMTP_USER (optional)
    - ALERT_SMTP_PASS (optional)
    - ALERT_SMTP_TLS  (default true)
    - ALERT_EMAIL_FROM
    - ALERT_EMAIL_TO  (comma-separated)
    """

    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    use_tls: bool = True
    email_from: str = ""
    email_to: list[str] = None  # type: ignore[assignment]

    @staticmethod
    def from_env() -> "EmailConfig | None":
        host = os.getenv("ALERT_SMTP_HOST", "").strip()
        if not host:
            return None
        port = int(os.getenv("ALERT_SMTP_PORT", "587").strip() or "587")
        user = os.getenv("ALERT_SMTP_USER", "").strip() or None
        password = os.getenv("ALERT_SMTP_PASS", "").strip() or None
        tls_raw = os.getenv("ALERT_SMTP_TLS", "true").strip().lower()
        use_tls = tls_raw not in ("0", "false", "no")
        email_from = os.getenv("ALERT_EMAIL_FROM", "").strip()
        to_raw = os.getenv("ALERT_EMAIL_TO", "").strip()
        email_to = [x.strip() for x in to_raw.split(",") if x.strip()]
        if not email_from or not email_to:
            # Config incomplete: treat as disabled rather than crashing the dashboard.
            return None
        return EmailConfig(
            host=host,
            port=port,
            user=user,
            password=password,
            use_tls=use_tls,
            email_from=email_from,
            email_to=email_to,
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

def _state_path(repo_root: Path) -> Path:
    return repo_root / "analysis" / "out" / "alert_state.json"


def _load_state(repo_root: Path) -> dict[str, Any]:
    p = _state_path(repo_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(repo_root: Path, state: dict[str, Any]) -> None:
    p = _state_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _send_email(cfg: EmailConfig, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.email_from
    msg["To"] = ", ".join(cfg.email_to)
    msg.set_content(body)

    with smtplib.SMTP(cfg.host, cfg.port, timeout=20) as server:
        if cfg.use_tls:
            server.starttls()
        if cfg.user and cfg.password:
            server.login(cfg.user, cfg.password)
        server.send_message(msg)


def snapshot(policy: TriggerPolicy) -> dict[str, Any]:
    repo_root = Path(os.getcwd()).resolve()
    email_cfg = EmailConfig.from_env()

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

    # Optional email alert (edge-triggered, with simple de-dupe / throttling).
    email_info: dict[str, Any] = {"enabled": email_cfg is not None}
    try:
        state = _load_state(repo_root)
        last_status = state.get("last_status")
        last_band = state.get("last_band_hit")
        last_sent = state.get("last_email_sent_at_utc")

        # Default: only email when we ENTER buy window, or hit a deeper band.
        should_send = False
        if email_cfg is not None and status == "BUY_WINDOW":
            if last_status != "BUY_WINDOW":
                should_send = True
            elif band_hit is not None and band_hit != last_band:
                # e.g., moved from -0.15 band to -0.20 band
                should_send = True

        # Throttle: at most one email per 6 hours.
        if should_send and last_sent:
            try:
                last_dt = datetime.fromisoformat(str(last_sent).replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 6 * 3600:
                    should_send = False
                    email_info["throttled"] = True
            except Exception:
                pass

        if should_send and email_cfg is not None:
            subject = f"[ALERT] BUY_WINDOW: SPX drawdown {dd_now:.1%}, VIX {vix_now:.2f}"
            body = (
                f"International Rotation Alert\n\n"
                f"Status: {status}\n"
                f"As of: {asof.strftime('%Y-%m-%d')}\n\n"
                f"S&P 500 level: {spx_now:.2f}\n"
                f"S&P 500 peak:  {peak_now:.2f}\n"
                f"Drawdown:      {dd_now:.2%}\n\n"
                f"VIX:           {vix_now:.2f} (min required {policy.vix_min:.2f})\n\n"
                f"Band hit: {band_hit}\n"
                f"Recommended deploy: {allocation}% of target international sleeve\n\n"
                f"Dashboard: (local) /dashboard.jsp\n"
            )
            _send_email(email_cfg, subject, body)
            email_info["sent"] = True
            email_info["sent_at_utc"] = datetime.now(timezone.utc).isoformat()
            state["last_email_sent_at_utc"] = email_info["sent_at_utc"]
        else:
            email_info["sent"] = False
            email_info["sent_at_utc"] = last_sent

        # Persist state regardless (for de-dupe)
        state["last_status"] = status
        state["last_band_hit"] = band_hit
        state["last_seen_at_utc"] = datetime.now(timezone.utc).isoformat()
        _save_state(repo_root, state)
    except Exception as e:
        # Never break the dashboard because email failed.
        email_info["error"] = str(e)

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
        "email": email_info,
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

