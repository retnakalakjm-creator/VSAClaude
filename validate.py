"""
Validation Harness: Run VSAClaude pipeline on historical data.

Tests:
1. Swing detection sanity (count, distribution)
2. Structural filtering effectiveness
3. Crash detection (2008, 2020)
4. Daily tag distribution and tier split
5. Trend classification across different market conditions

Usage:
    python validate.py --data-dir stocks/ --tickers HDFCBANK RELIANCE TATASTEEL TITAN DLF
    python validate.py --data-dir stocks/ --all  # all available files in dir
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import pandas as pd

from data_loader import load_stock_data, load_multiple_stocks
from swing_engine import detect_swings
from structure_filter import filter_structural_swings
from trend_analyzer import analyze_trend, classify_swings
from daily_tagger import build_daily_contexts, tag_daily_bars
from models import Swing, StructuralSwing, TrendDirection


# Known market crash windows to validate against
CRASH_WINDOWS = [
    ("2008 Financial Crisis", "2008-01-01", "2008-11-30"),
    ("2020 COVID Crash", "2020-02-01", "2020-04-15"),
]


def collapse_to_regime_segments(structural_swings: List[StructuralSwing],
                                 df: pd.DataFrame) -> List[Dict]:
    """
    Collapse the swing sequence into contiguous trend segments.
    Each segment = consecutive bars with the same trend direction.
    """
    if not structural_swings:
        return []
    
    classifications = classify_swings(structural_swings)
    if not classifications:
        return []
    
    segments = []
    current_direction = None
    segment_start_idx = 0
    segment_start_price = None
    
    for i, clf in enumerate(classifications):
        swing_idx = structural_swings[i].swing.bar_index
        swing_price = structural_swings[i].swing.price
        
        # Determine direction from this swing
        if clf.is_higher_high or clf.is_higher_low:
            direction = "UP"
        elif clf.is_lower_high or clf.is_lower_low:
            direction = "DOWN"
        else:
            direction = "RANGE"
        
        # If direction changes, close the previous segment
        if direction != current_direction and current_direction is not None:
            segment_end_idx = swing_idx
            segment_end_price = swing_price
            segment_end_date = df.index[segment_end_idx]
            segment_start_date = df.index[segment_start_idx]
            
            pct_return = (segment_end_price - segment_start_price) / segment_start_price * 100 if segment_start_price else 0
            duration_bars = segment_end_idx - segment_start_idx
            
            segments.append({
                'direction': current_direction,
                'start_date': segment_start_date.date(),
                'end_date': segment_end_date.date(),
                'start_price': round(segment_start_price, 2),
                'end_price': round(segment_end_price, 2),
                'pct_return': round(pct_return, 2),
                'bars': duration_bars,
            })
        
        # Move to next segment if needed
        if direction != current_direction:
            current_direction = direction
            segment_start_idx = swing_idx
            segment_start_price = swing_price
    
    return segments


def check_crash_detection(segments: List[Dict], window_name: str, start: str, end: str) -> str:
    """Check if a downtrend was detected during a known crash window."""
    start_dt = pd.Timestamp(start).date()
    end_dt = pd.Timestamp(end).date()
    
    downtrend_segments = [s for s in segments if s['direction'] == "DOWN"]
    overlapping = [s for s in downtrend_segments 
                   if s['start_date'] <= end_dt and s['end_date'] >= start_dt]
    
    if overlapping:
        return f"  ✓ DETECTED {window_name}: {len(overlapping)} downtrend segment(s)"
    else:
        return f"  ✗ MISSED {window_name} ({start} to {end})"


def validate_ticker(ticker: str, df: pd.DataFrame, verbose: bool = False) -> Dict:
    """
    Run full pipeline on a ticker and collect diagnostic metrics.
    """
    results = {
        'ticker': ticker,
        'bars': len(df),
        'date_range': f"{df.index[0].date()} to {df.index[-1].date()}",
    }
    
    # Step 1: Detect swings
    swings = detect_swings(df)
    results['raw_swings'] = len(swings)
    
    # Step 2: Filter to structural
    structural_swings = filter_structural_swings(df, swings)
    results['structural_swings'] = len(structural_swings)
    
    if len(structural_swings) > 0:
        results['swing_filter_rate'] = f"{100 * len(structural_swings) / len(swings):.1f}%"
    else:
        results['swing_filter_rate'] = "0%"
    
    # Step 3: Analyze trend
    trend = analyze_trend(structural_swings)
    results['trend_direction'] = trend.direction.name
    results['trend_state'] = trend.state.name
    results['trend_strength'] = f"{trend.strength:.2%}"
    results['trend_confidence'] = f"{trend.confidence:.2%}"
    results['bullish_swings'] = trend.bullish_swings
    results['bearish_swings'] = trend.bearish_swings
    
    # Step 4: Detect daily tags
    daily_contexts = build_daily_contexts(df)
    daily_tags = tag_daily_bars(daily_contexts)
    results['daily_tags'] = len(daily_tags)
    
    # Tag tier distribution
    major = sum(1 for t in daily_tags if t.tier.value == 'major_signal')
    minor = sum(1 for t in daily_tags if t.tier.value == 'minor_observation')
    results['tags_major'] = major
    results['tags_minor'] = minor
    results['tags_pct_major'] = f"{100 * major / len(daily_tags):.1f}%" if daily_tags else "0%"
    
    # Step 5: Check crash detection
    segments = collapse_to_regime_segments(structural_swings, df)
    results['regime_segments'] = len(segments)
    
    crash_checks = []
    for window_name, start, end in CRASH_WINDOWS:
        check = check_crash_detection(segments, window_name, start, end)
        crash_checks.append(check)
    results['crash_checks'] = crash_checks
    
    return results


def format_report(all_results: List[Dict]) -> str:
    """Format validation results for display."""
    lines = [
        "\n" + "=" * 100,
        "VSACLAUDE HISTORICAL VALIDATION REPORT",
        "=" * 100,
        "",
    ]
    
    for results in all_results:
        lines.append(f"\nTICKER: {results['ticker']}")
        lines.append(f"  Data range: {results['date_range']} ({results['bars']} bars)")
        lines.append(f"  Raw swings: {results['raw_swings']} → Structural: {results['structural_swings']} "
                     f"(filter rate: {results['swing_filter_rate']})")
        lines.append(f"  Trend: {results['trend_direction']} ({results['trend_state']}) "
                     f"strength={results['trend_strength']} confidence={results['trend_confidence']}")
        lines.append(f"  Swings: {results['bullish_swings']} bullish, {results['bearish_swings']} bearish")
        lines.append(f"  Daily tags: {results['daily_tags']} total ({results['tags_major']} major, "
                     f"{results['tags_minor']} minor) — {results['tags_pct_major']} are MAJOR_SIGNAL")
        lines.append(f"  Regime segments: {results['regime_segments']}")
        for check in results['crash_checks']:
            lines.append(check)
    
    lines.append("\n" + "=" * 100 + "\n")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Validate VSAClaude on historical data")
    parser.add_argument('--data-dir', default='stocks', help='Directory containing CSV files')
    parser.add_argument('--tickers', nargs='+', help='Specific tickers to validate')
    parser.add_argument('--all', action='store_true', help='Load all CSV files from data-dir')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Determine which tickers to load
    if args.all:
        # Find all CSV files in data-dir
        data_dir = Path(args.data_dir)
        csv_files = list(data_dir.glob('*.csv'))
        tickers = [f.stem.split('.')[0].upper() for f in csv_files]
        print(f"Found {len(tickers)} CSV files: {', '.join(sorted(tickers[:5]))}{'...' if len(tickers) > 5 else ''}")
    elif args.tickers:
        tickers = args.tickers
    else:
        # Default set
        tickers = ["HDFCBANK", "RELIANCE", "TATASTEEL", "TITAN", "DLF"]
    
    # Load data
    print(f"\nLoading data from {args.data_dir}/...")
    data = load_multiple_stocks(args.data_dir, tickers)
    
    if not data:
        print("ERROR: No data loaded. Check --data-dir and --tickers.")
        sys.exit(1)
    
    print(f"Loaded {len(data)} stocks.\n")
    
    # Validate each ticker
    print("Running validation pipeline...")
    all_results = []
    for ticker in sorted(data.keys()):
        print(f"  {ticker}...", end=" ", flush=True)
        try:
            results = validate_ticker(ticker, data[ticker], args.verbose)
            all_results.append(results)
            print("✓")
        except Exception as e:
            print(f"✗ ({e})")
    
    # Report
    report = format_report(all_results)
    print(report)
    
    # Summary statistics
    print("\nSUMMARY")
    print("=" * 100)
    avg_filter_rate = sum(float(r['swing_filter_rate'].rstrip('%')) for r in all_results) / len(all_results)
    avg_tags_pct = sum(float(r['tags_pct_major'].rstrip('%')) for r in all_results) / len(all_results)
    
    print(f"Average swing filter rate: {avg_filter_rate:.1f}%")
    print(f"Average MAJOR_SIGNAL rate: {avg_tags_pct:.1f}%")
    print(f"Crash detection: ", end="")
    crash_hits = sum(1 for r in all_results for check in r['crash_checks'] if "✓" in check)
    total_crashes = len(CRASH_WINDOWS) * len(all_results)
    print(f"{crash_hits}/{total_crashes} windows detected")


if __name__ == "__main__":
    main()
