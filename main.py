"""
VSAClaude Main Orchestrator

Runs the complete analysis pipeline:
  1. Swing Engine: detect raw pivots via ZigZag
  2. Structure Filter: keep only significant swings
  3. Trend Analyzer: classify swings and determine trend
  4. Daily Tagger: detect daily bar patterns
  5. Output: formatted results

Usage:
    python main.py <ticker> <data.csv>
"""

import sys
import pandas as pd
from datetime import datetime
from pathlib import Path

from swing_engine import detect_swings
from structure_filter import filter_structural_swings
from trend_analyzer import analyze_trend
from daily_tagger import build_daily_contexts, tag_daily_bars
from models import ScanResult


def load_data(filepath: str) -> pd.DataFrame:
    """Load OHLCV data from CSV."""
    df = pd.read_csv(filepath, parse_dates=['date'])
    df.set_index('date', inplace=True)
    df = df.sort_index()
    return df


def run_scan(symbol: str, df: pd.DataFrame) -> ScanResult:
    """
    Run complete analysis pipeline on a stock's OHLCV data.
    
    Args:
        symbol: ticker symbol
        df: OHLCV DataFrame with 'date' index
    
    Returns:
        ScanResult with all analysis layers
    """
    # Step 1: Detect raw swings
    print(f"[{symbol}] Detecting swings...", file=sys.stderr)
    swings = detect_swings(df)
    print(f"[{symbol}] Found {len(swings)} raw swings", file=sys.stderr)
    
    # Step 2: Filter to structural swings only
    print(f"[{symbol}] Filtering for structural significance...", file=sys.stderr)
    structural_swings = filter_structural_swings(df, swings)
    print(f"[{symbol}] {len(structural_swings)} structural swings", file=sys.stderr)
    
    # Step 3: Analyze trend from structural swings
    print(f"[{symbol}] Analyzing trend...", file=sys.stderr)
    trend = analyze_trend(structural_swings)
    print(f"[{symbol}] Trend: {trend.direction.name} ({trend.state.name}), "
          f"strength={trend.strength:.2f}, confidence={trend.confidence:.2f}", file=sys.stderr)
    
    # Step 4: Detect daily bar patterns
    print(f"[{symbol}] Tagging daily bars...", file=sys.stderr)
    daily_contexts = build_daily_contexts(df)
    daily_tags = tag_daily_bars(daily_contexts)
    print(f"[{symbol}] Found {len(daily_tags)} daily signals", file=sys.stderr)
    
    # Build result
    as_of_date = df.index[-1]
    result = ScanResult(
        symbol=symbol,
        as_of_date=as_of_date,
        swings=tuple(structural_swings),
        background=None,  # TODO: evidence aggregation
        trend=trend,
        daily_tags=tuple(daily_tags),
    )
    
    return result


def format_result(result: ScanResult) -> str:
    """Format ScanResult for display."""
    lines = [
        f"\n{'='*70}",
        f"SCAN RESULT: {result.symbol} as of {result.as_of_date.date()}",
        f"{'='*70}",
        "",
        f"STRUCTURAL SWINGS: {len(result.swings)} confirmed",
        f"  Direction: {result.trend.direction.name}",
        f"  State: {result.trend.state.name}",
        f"  Strength: {result.trend.strength:.2%}",
        f"  Confidence: {result.trend.confidence:.2%}",
        f"  Bullish swings: {result.trend.bullish_swings}",
        f"  Bearish swings: {result.trend.bearish_swings}",
        "",
        f"DAILY SIGNALS: {len(result.daily_tags)} tags",
    ]
    
    if result.daily_tags:
        lines.append("  " + "-" * 60)
        for tag in sorted(result.daily_tags, key=lambda t: t.date)[-10:]:  # last 10 tags
            lines.append(f"    {tag.date.date()}: {tag.code.value:35s} {tag.tier.value:20s} "
                         f"(strength={tag.strength:.2f})")
    
    lines.append(f"{'='*70}\n")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("Usage: python main.py <ticker> <data.csv>")
        print("Example: python main.py HDFCBANK data/HDFCBANK.csv")
        sys.exit(1)
    
    ticker = sys.argv[1]
    filepath = sys.argv[2]
    
    # Load data
    print(f"Loading {filepath}...", file=sys.stderr)
    df = load_data(filepath)
    print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}", file=sys.stderr)
    
    # Run scan
    result = run_scan(ticker, df)
    
    # Display result
    print(format_result(result))


if __name__ == "__main__":
    main()
