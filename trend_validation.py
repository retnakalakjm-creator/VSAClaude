"""
TREND VALIDATION: audit MAJOR_TREND against real price history
-----------------------------------------------------------------
Not part of the core pipeline -- this is a diagnostic tool to sanity
check the swing-pivot trend classifier (tagging_engine.py) against
actual historical price behavior, before trusting it in later steps.

Collapses the bar-by-bar MAJOR_TREND label into contiguous REGIME
SEGMENTS (a run of consecutive weeks with the same label), then reports
the price return and duration of each segment. This lets us objectively
check two things:
  1. Do STRONG_UPTREND segments actually show positive returns, and
     STRONG_DOWNTREND segments negative ones? (sanity check on direction)
  2. Do known macro shocks (2008 financial crisis, 2020 COVID crash)
     actually get flagged as downtrends around when they happened?
     (sanity check on timing)
"""

import pandas as pd
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe
from weekly_metrics import build_weekly_dataset
from tagging_engine import tag_all_tickers

VALIDATION_TICKERS = ["HDFCBANK", "RELIANCE", "TATASTEEL", "TITAN", "DLF"]

# Known macro shock windows to cross-check against (India/global events
# that should show up as STRONG_DOWNTREND somewhere in this window)
KNOWN_CRASH_WINDOWS = [
    ("2008 Global Financial Crisis", "2008-01-01", "2008-11-30"),
    ("2020 COVID Crash", "2020-02-01", "2020-04-15"),
]


def collapse_to_regimes(tagged_df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapses row-by-row MAJOR_TREND into contiguous segments:
    (label, start_date, end_date, start_close, end_close, pct_return, weeks)
    """
    df = tagged_df[["week_start", "close", "MAJOR_TREND"]].copy()
    df["regime_id"] = (df["MAJOR_TREND"] != df["MAJOR_TREND"].shift(1)).cumsum()

    segments = []
    for regime_id, group in df.groupby("regime_id"):
        label = group["MAJOR_TREND"].iloc[0]
        start_date = group["week_start"].iloc[0]
        end_date = group["week_start"].iloc[-1]
        start_close = group["close"].iloc[0]
        end_close = group["close"].iloc[-1]
        pct_return = (end_close - start_close) / start_close * 100
        segments.append({
            "label": label,
            "start_date": start_date.date(),
            "end_date": end_date.date(),
            "weeks": len(group),
            "start_close": round(start_close, 2),
            "end_close": round(end_close, 2),
            "pct_return": round(pct_return, 2),
        })

    return pd.DataFrame(segments)


def check_crash_window(regimes_df: pd.DataFrame, window_name: str, start: str, end: str) -> str:
    """
    Checks whether STRONG_DOWNTREND or WEAK_DOWNTREND appears anywhere
    overlapping the given date window. Fast, violent crashes may only
    reach WEAK_DOWNTREND before recovering, since STRONG requires full
    two-pivot confirmation on both legs -- that's a legitimate outcome,
    not a miss, as long as SOME downtrend read shows up during the window.
    """
    start_dt = pd.Timestamp(start).date()
    end_dt = pd.Timestamp(end).date()

    overlapping = regimes_df[
        (regimes_df["label"].isin(["STRONG_DOWNTREND", "WEAK_DOWNTREND"])) &
        (regimes_df["start_date"] <= end_dt) &
        (regimes_df["end_date"] >= start_dt)
    ]

    if len(overlapping) > 0:
        rows = overlapping.to_string(index=False)
        return f"  [DETECTED] {window_name}:\n{rows}\n"
    else:
        return f"  [MISSED] {window_name} ({start} to {end}) -- no STRONG/WEAK_DOWNTREND segment found overlapping this window\n"


if __name__ == "__main__":
    stock_data = ingest_all_stocks()
    passed_data, _ = filter_universe(stock_data)
    weekly_data = build_weekly_dataset(passed_data)
    tagged_data = tag_all_tickers(weekly_data)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    all_segments = {}

    for ticker in VALIDATION_TICKERS:
        if ticker not in tagged_data:
            print(f"WARNING: {ticker} not found in tagged data, skipping.")
            continue

        regimes = collapse_to_regimes(tagged_data[ticker])
        all_segments[ticker] = regimes

        print("=" * 100)
        print(f"TICKER: {ticker}  --  {len(regimes)} regime segments over "
              f"{tagged_data[ticker]['week_start'].min().date()} to {tagged_data[ticker]['week_start'].max().date()}")
        print("=" * 100)

        # Directional sanity check: average return by label
        direction_check = regimes.groupby("label").agg(
            count=("pct_return", "size"),
            avg_return_pct=("pct_return", "mean"),
            avg_duration_weeks=("weeks", "mean"),
        ).round(2)
        print("\nDirectional sanity check (avg return should be positive for "
              "uptrends, negative for downtrends):")
        print(direction_check.to_string())

        # Whipsaw check: how many segments last only 1-2 weeks (potential noise)
        whipsaws = (regimes["weeks"] <= 2).sum()
        print(f"\nWhipsaw check: {whipsaws} / {len(regimes)} segments lasted <=2 weeks "
              f"({whipsaws/len(regimes)*100:.1f}%)")

        # Macro crash window cross-check
        print(f"\nMacro shock timing check for {ticker}:")
        for window_name, start, end in KNOWN_CRASH_WINDOWS:
            print(check_crash_window(regimes, window_name, start, end))

    print("\n" + "=" * 100)
    print("LONGEST STRONG_UPTREND AND STRONG_DOWNTREND SEGMENTS ACROSS ALL 5 TICKERS")
    print("=" * 100)
    combined = pd.concat(
        [df.assign(ticker=t) for t, df in all_segments.items()], ignore_index=True
    )
    for label in ["STRONG_UPTREND", "STRONG_DOWNTREND"]:
        subset = combined[combined["label"] == label].sort_values("weeks", ascending=False).head(5)
        print(f"\nTop 5 longest {label} segments:")
        print(subset[["ticker", "start_date", "end_date", "weeks", "pct_return"]].to_string(index=False))
