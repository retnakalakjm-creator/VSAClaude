"""Runs trend_validation.py's same regime-segment audit, but against
structural_swings.py's output instead of the old tagging_engine trend
logic -- so results are directly comparable to the earlier validation."""
import pandas as pd
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe
from weekly_metrics import build_weekly_dataset
from structural_swings import detect_structural_swings
from trend_validation import (
    VALIDATION_TICKERS, KNOWN_CRASH_WINDOWS, collapse_to_regimes, check_crash_window
)

stock_data = ingest_all_stocks()
passed_data, _ = filter_universe(stock_data)
weekly_data = build_weekly_dataset(passed_data)

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", None)

all_segments = {}
for ticker in VALIDATION_TICKERS:
    tagged = detect_structural_swings(weekly_data[ticker])
    regimes = collapse_to_regimes(tagged)
    all_segments[ticker] = regimes

    print("=" * 100)
    print(f"TICKER: {ticker} -- {len(regimes)} regime segments")
    print("=" * 100)
    direction_check = regimes.groupby("label").agg(
        count=("pct_return", "size"), avg_return_pct=("pct_return", "mean"),
        avg_duration_weeks=("weeks", "mean"),
    ).round(2)
    print(direction_check.to_string())
    whipsaws = (regimes["weeks"] <= 2).sum()
    print(f"Whipsaw check: {whipsaws}/{len(regimes)} ({whipsaws/len(regimes)*100:.1f}%)")
    for window_name, start, end in KNOWN_CRASH_WINDOWS:
        print(check_crash_window(regimes, window_name, start, end))
