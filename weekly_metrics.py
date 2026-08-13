"""
STEP 3: WEEKLY TIME-DOWNSAMPLING & VOLATILITY-ADJUSTED METRICS
-----------------------------------------------------------------
Goal: Compress verified daily bars (post liquidity-filter) into weekly
OHLCV bars, then derive the raw structural building blocks every later
tag in Step 4 will depend on:

  Spread          = High - Low
  CLV             = (Close - Low) / (Spread + 1e-10)   [0=close at low, 1=close at high]
  Spread_Z        = (Spread - 20wk rolling mean) / 20wk rolling std
  Vol_Z           = (Volume - 20wk rolling mean) / 20wk rolling std

Weekly bars use NSE's trading week (Mon-Fri), anchored on 'W-FRI' so
each week's bar closes on its actual last traded Friday, not a
calendar-arbitrary Sunday.

This layer depends on Step 1 (ingestion) and Step 2 (liquidity_filters)
and does not modify either.
"""

import pandas as pd
import numpy as np
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe

ROLLING_WINDOW = 20  # weeks


def resample_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse a daily OHLCV DataFrame into weekly bars.
    Week boundary = Friday close (NSE trading week), via 'W-FRI'.
    """
    df = daily_df.set_index("date")

    weekly = df.resample("W-FRI").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })

    # Drop any week with no trading data at all (e.g. holiday-only week)
    weekly = weekly.dropna(subset=["open", "high", "low", "close"])
    weekly = weekly[weekly["volume"] > 0]

    weekly = weekly.reset_index().rename(columns={"date": "week_end"})

    # TradingView-style display convention: label the bar by the week's
    # FIRST trading day (Monday), not its last (Friday). week_end is
    # DELIBERATELY KEPT alongside it -- Step 5's daily-to-weekly merge
    # relies on the actual Friday completion date to know when a week's
    # background genuinely becomes knowable (the following trading day).
    # Relabeling for display must never be confused with when the data
    # was actually complete -- that would risk quietly reintroducing
    # look-ahead bias into Step 5. week_start is for display/reporting
    # only; week_end remains the source of truth for timing logic.
    weekly["week_start"] = weekly["week_end"] - pd.Timedelta(days=4)
    weekly = weekly[["week_start", "week_end", "open", "high", "low", "close", "volume"]]
    return weekly


def _rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """
    For each bar, returns what fraction (0.0-1.0) of the trailing
    `window` bars (INCLUDING the current bar) had a value <= the
    current bar's value. 1.0 = highest value in the window,
    0.0 = lowest value in the window.

    This is the primary normalization method (chosen over Z-score)
    because volume/spread distributions are right-skewed, not normal,
    and because percentile rank is far less distorted by a single
    outlier bar sitting inside the rolling window -- a Z-score's mean
    and std dev get dragged around by one freak bar, but a percentile
    rank just gives that bar the top rank and rolls on cleanly.
    """
    def pct_rank_of_last(window_values):
        last = window_values[-1]
        return (window_values <= last).mean()

    return series.rolling(window=window).apply(pct_rank_of_last, raw=True)


def add_volatility_metrics(weekly_df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds Spread, CLV, 20-week rolling PERCENTILE RANKS (primary
    normalization) for Spread and Volume, and 20-week rolling Z-scores
    (kept as a secondary continuous-magnitude feature, used only by
    tags that need to combine spread and volume on one numeric scale,
    e.g. ABSORPTION).
    """
    df = weekly_df.copy()

    df["spread"] = df["high"] - df["low"]
    df["clv"] = (df["close"] - df["low"]) / (df["spread"] + 1e-10)

    # --- PRIMARY: rolling percentile rank ---
    df["spread_pctile"] = _rolling_percentile_rank(df["spread"], ROLLING_WINDOW)
    df["vol_pctile"] = _rolling_percentile_rank(df["volume"], ROLLING_WINDOW)

    # --- SECONDARY: Z-score, kept for magnitude-sensitive calcs like ABSORPTION ---
    spread_mean = df["spread"].rolling(window=ROLLING_WINDOW).mean()
    spread_std = df["spread"].rolling(window=ROLLING_WINDOW).std()
    df["spread_z"] = (df["spread"] - spread_mean) / spread_std

    vol_mean = df["volume"].rolling(window=ROLLING_WINDOW).mean()
    vol_std = df["volume"].rolling(window=ROLLING_WINDOW).std()
    df["vol_z"] = (df["volume"] - vol_mean) / vol_std

    return df


def build_weekly_dataset(stock_data: dict) -> dict:
    """
    Runs resample_to_weekly + add_volatility_metrics across every ticker.
    Returns {ticker: weekly_df_with_metrics}
    """
    weekly_data = {}
    for ticker, daily_df in stock_data.items():
        weekly = resample_to_weekly(daily_df)
        weekly = add_volatility_metrics(weekly)
        weekly_data[ticker] = weekly
    return weekly_data


if __name__ == "__main__":
    stock_data = ingest_all_stocks()
    passed_data, diagnostic_df = filter_universe(stock_data)

    print(f"\n{len(passed_data)} ticker(s) passed liquidity filters -> proceeding to weekly downsampling.\n")

    weekly_data = build_weekly_dataset(passed_data)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")

    print("=" * 100)
    print("STEP 3: WEEKLY BAR SUMMARY (row counts + latest values)")
    print("=" * 100)

    summary_rows = []
    for ticker, wdf in weekly_data.items():
        last = wdf.iloc[-1]
        summary_rows.append({
            "ticker": ticker,
            "weekly_bars": len(wdf),
            "last_week_start": last["week_start"].date(),
            "last_close": round(last["close"], 2),
            "last_spread": round(last["spread"], 2),
            "last_clv": round(last["clv"], 3),
            "last_spread_pctile": round(last["spread_pctile"], 3) if pd.notna(last["spread_pctile"]) else None,
            "last_vol_pctile": round(last["vol_pctile"], 3) if pd.notna(last["vol_pctile"]) else None,
            "last_spread_z": round(last["spread_z"], 3) if pd.notna(last["spread_z"]) else None,
            "last_vol_z": round(last["vol_z"], 3) if pd.notna(last["vol_z"]) else None,
        })

    summary_df = pd.DataFrame(summary_rows).sort_values("ticker").reset_index(drop=True)
    print(summary_df.to_string(index=False))

    print("\n" + "=" * 100)
    print("DETAILED SAMPLE: HDFCBANK last 8 weekly bars (full metric set)")
    print("=" * 100)
    if "HDFCBANK" in weekly_data:
        cols = ["week_start", "open", "high", "low", "close", "volume",
                "spread", "clv", "spread_pctile", "vol_pctile", "spread_z", "vol_z"]
        print(weekly_data["HDFCBANK"][cols].tail(8).to_string(index=False))

    print("\nNote: spread_z / vol_z will show NaN for the first "
          f"{ROLLING_WINDOW-1} weekly bars of each ticker -- this is expected, "
          "since a 20-week rolling window needs 20 prior weeks to populate.")
