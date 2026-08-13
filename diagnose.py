"""
Diagnostic Analyzer: investigates why daily tags fire and how to calibrate tiering.

Runs on a single ticker and produces a detailed breakdown of tag firing patterns,
extremity scores, and recommendations for threshold adjustment.

Usage:
    python diagnose.py --data-dir stocks/ --ticker HDFCBANK
"""

import sys
import argparse
import pandas as pd
from typing import List
import statistics

from data_loader import load_stock_data
from daily_tagger import build_daily_contexts
from models import DailyTag, SignalTier, EvidenceCode


def diagnose_daily_tags(ticker: str, df: pd.DataFrame, sample_size: int = 100) -> None:
    """
    Analyze daily tags in detail: which patterns fire most, their strength distribution,
    and recommendations for threshold tuning.
    """
    print(f"\n{'='*100}")
    print(f"DIAGNOSTIC: {ticker} Daily Tag Analysis")
    print(f"{'='*100}\n")
    
    # Build contexts
    daily_contexts = build_daily_contexts(df)
    
    # Manually re-tag with detailed tracking
    tags_fired = {code.value: [] for code in EvidenceCode}
    tag_strengths = {code.value: [] for code in EvidenceCode}
    
    for context in daily_contexts:
        # NO_SUPPLY
        if context.direction < 0 and context.spread_percentile < 0.35 and context.volume_percentile < 0.40:
            strength = (1.0 - context.spread_percentile + 1.0 - context.volume_percentile) / 2
            tags_fired['no_supply'].append({
                'date': context.date,
                'strength': strength,
                'vol_pctile': context.volume_percentile,
                'spread_pctile': context.spread_percentile,
            })
            tag_strengths['no_supply'].append(strength)
        
        # NO_DEMAND
        if context.direction > 0 and context.spread_percentile < 0.35 and context.volume_percentile < 0.40:
            strength = (1.0 - context.spread_percentile + 1.0 - context.volume_percentile) / 2
            tags_fired['no_demand'].append({
                'date': context.date,
                'strength': strength,
                'vol_pctile': context.volume_percentile,
                'spread_pctile': context.spread_percentile,
            })
            tag_strengths['no_demand'].append(strength)
        
        # STOPPING_VOLUME
        if context.volume_percentile >= 0.85 and context.close_location_value >= 0.65:
            vol_ext = (context.volume_percentile - 0.85) / 0.15
            clv_ext = (context.close_location_value - 0.65) / 0.35
            strength = (vol_ext + clv_ext) / 2
            tags_fired['stopping_volume'].append({
                'date': context.date,
                'strength': strength,
                'vol_pctile': context.volume_percentile,
                'clv': context.close_location_value,
            })
            tag_strengths['stopping_volume'].append(strength)
        
        # SELLING_CLIMAX
        if (context.volume_percentile >= 0.85 and context.spread_percentile >= 0.85 and 
            context.close_location_value < 0.35):
            vol_ext = (context.volume_percentile - 0.85) / 0.15
            spread_ext = (context.spread_percentile - 0.85) / 0.15
            clv_ext = (0.35 - context.close_location_value) / 0.35
            strength = (vol_ext + spread_ext + clv_ext) / 3
            tags_fired['selling_climax'].append({
                'date': context.date,
                'strength': strength,
                'vol_pctile': context.volume_percentile,
                'spread_pctile': context.spread_percentile,
                'clv': context.close_location_value,
            })
            tag_strengths['selling_climax'].append(strength)
        
        # BUYING_CLIMAX
        if (context.volume_percentile >= 0.85 and context.spread_percentile >= 0.85 and 
            context.close_location_value < 0.65 and context.direction > 0):
            vol_ext = (context.volume_percentile - 0.85) / 0.15
            spread_ext = (context.spread_percentile - 0.85) / 0.15
            clv_weakness = (0.65 - context.close_location_value) / 0.65
            strength = (vol_ext + spread_ext + clv_weakness) / 3
            tags_fired['buying_climax'].append({
                'date': context.date,
                'strength': strength,
                'vol_pctile': context.volume_percentile,
                'spread_pctile': context.spread_percentile,
                'clv': context.close_location_value,
            })
            tag_strengths['buying_climax'].append(strength)
    
    # Report by tag type
    print(f"TAG FIRING ANALYSIS: which patterns occur and at what strength?\n")
    
    for code_name in sorted(tags_fired.keys()):
        fired = tags_fired[code_name]
        strengths = tag_strengths[code_name]
        
        if not fired:
            print(f"{code_name:25s}: 0 instances")
            continue
        
        avg_strength = statistics.mean(strengths)
        median_strength = statistics.median(strengths)
        min_strength = min(strengths)
        max_strength = max(strengths)
        pct_of_bars = 100 * len(fired) / len(daily_contexts)
        
        print(f"{code_name:25s}: {len(fired):4d} instances ({pct_of_bars:5.2f}% of bars)")
        print(f"  Strength range: {min_strength:.3f} → {max_strength:.3f}")
        print(f"  Strength stats: mean={avg_strength:.3f}, median={median_strength:.3f}")
        
        # How many would be MAJOR vs MINOR at different thresholds?
        for threshold in [0.30, 0.40, 0.50, 0.60]:
            major_count = sum(1 for s in strengths if s >= threshold)
            major_pct = 100 * major_count / len(strengths)
            print(f"    At threshold {threshold}: {major_pct:5.1f}% would be MAJOR")
        print()
    
    print("\n" + "="*100)
    print("RECOMMENDATIONS")
    print("="*100 + "\n")
    
    total_tags = sum(len(v) for v in tags_fired.values())
    total_major_at_40 = sum(
        sum(1 for s in tag_strengths[code] if s >= 0.40)
        for code in tag_strengths
    )
    
    current_major_pct = 100 * total_major_at_40 / total_tags if total_tags > 0 else 0
    
    print(f"Current state (threshold=0.40):")
    print(f"  Total daily tags: {total_tags}")
    print(f"  MAJOR_SIGNAL count: {total_major_at_40} ({current_major_pct:.1f}%)")
    print(f"  Target: 40-60% MAJOR_SIGNAL\n")
    
    if current_major_pct > 65:
        print("ISSUE: Too many MAJOR_SIGNAL tags (> 65%)")
        print("  This means thresholds are too easy to cross.\n")
        
        # Find the threshold that would give us ~50% MAJOR
        for threshold in [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
            major_at_this = sum(
                sum(1 for s in tag_strengths[code] if s >= threshold)
                for code in tag_strengths
            )
            pct = 100 * major_at_this / total_tags if total_tags > 0 else 0
            print(f"  At threshold {threshold}: {pct:5.1f}% MAJOR")
        
        print("\n  RECOMMENDATION: Increase TIER_MAJOR_THRESHOLD from 0.40 to 0.55-0.60")
        print("  This will make it harder to achieve MAJOR_SIGNAL status.\n")
    
    elif current_major_pct < 30:
        print("ISSUE: Too few MAJOR_SIGNAL tags (< 30%)")
        print("  Thresholds are too strict.\n")
        print("  RECOMMENDATION: Decrease TIER_MAJOR_THRESHOLD from 0.40 to 0.25-0.30")
    
    else:
        print(f"HEALTHY: {current_major_pct:.1f}% MAJOR_SIGNAL (target: 40-60%)")


def main():
    parser = argparse.ArgumentParser(description="Diagnose daily tag firing patterns")
    parser.add_argument('--data-dir', default='stocks', help='Directory containing CSV files')
    parser.add_argument('--ticker', required=True, help='Ticker to diagnose')
    
    args = parser.parse_args()
    
    # Load data
    filepath = f"{args.data_dir}/{args.ticker}.csv"
    try:
        df = load_stock_data(filepath)
        print(f"Loaded {args.ticker}: {len(df)} bars")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    
    # Diagnose
    diagnose_daily_tags(args.ticker, df)


if __name__ == "__main__":
    main()
