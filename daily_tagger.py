"""
Daily Tagger: detects daily bar patterns with Major/Minor/Neutral tiering.

This module detects VSA/Wyckoff patterns on individual daily bars:
- No Supply / No Demand (narrow range, low volume)
- Stopping Volume (volume spike with strong close)
- Selling/Buying Climax (climactic volume + price action)
- Spring / Upthrust (range breaks and false breaks)

Each tag is tiered based on how convincingly it meets its thresholds.
"""

from typing import List, Tuple
import pandas as pd
import numpy as np

from models import DailyTag, DailyContext, EvidenceCode, SignalTier
from config import (
    DAILY_LOOKBACK_WINDOW,
    DAILY_HIGH_VOL_PCTILE,
    DAILY_HIGH_SPREAD_PCTILE,
    DAILY_LOW_VOL_PCTILE,
    DAILY_LOW_SPREAD_PCTILE,
    DAILY_STRONG_CLV,
    DAILY_WEAK_CLV,
    TIER_MAJOR_THRESHOLD,
)


def build_daily_contexts(df: pd.DataFrame) -> List[DailyContext]:
    """
    Build enriched daily bar contexts with computed metrics.
    """
    contexts: List[DailyContext] = []
    
    spread = df['high'] - df['low']
    volume_ma = df['volume'].rolling(window=DAILY_LOOKBACK_WINDOW, min_periods=5).mean()
    spread_ma = spread.rolling(window=DAILY_LOOKBACK_WINDOW, min_periods=5).mean()
    
    # Percentile ranks
    volume_pctile = df['volume'].rolling(window=DAILY_LOOKBACK_WINDOW, min_periods=5).apply(
        lambda x: (x.iloc[-1] <= x).sum() / len(x) if len(x) > 0 else 0.0, raw=False
    )
    spread_pctile = spread.rolling(window=DAILY_LOOKBACK_WINDOW, min_periods=5).apply(
        lambda x: (x.iloc[-1] <= x).sum() / len(x) if len(x) > 0 else 0.0, raw=False
    )
    
    for i in range(len(df)):
        date = df.index[i]
        clv = (df['close'].iloc[i] - df['low'].iloc[i]) / (spread.iloc[i] + 1e-10)
        direction = 1 if df['close'].iloc[i] > df['open'].iloc[i] else (-1 if df['close'].iloc[i] < df['open'].iloc[i] else 0)
        
        context = DailyContext(
            date=date,
            bar_index=i,
            open=df['open'].iloc[i],
            high=df['high'].iloc[i],
            low=df['low'].iloc[i],
            close=df['close'].iloc[i],
            volume=df['volume'].iloc[i],
            spread=spread.iloc[i],
            close_location_value=clv,
            volume_percentile=volume_pctile.iloc[i] or 0.0,
            spread_percentile=spread_pctile.iloc[i] or 0.0,
            direction=direction,
        )
        contexts.append(context)
    
    return contexts


def tag_daily_bars(contexts: List[DailyContext]) -> List[DailyTag]:
    """
    Detect VSA patterns on daily bars and assign Major/Minor/Neutral tiers.
    """
    tags: List[DailyTag] = []
    
    for context in contexts:
        # Check each pattern
        no_supply_tag = _check_no_supply(context)
        no_demand_tag = _check_no_demand(context)
        stopping_vol_tag = _check_stopping_volume(context)
        selling_climax_tag = _check_selling_climax(context)
        buying_climax_tag = _check_buying_climax(context)
        
        # Collect fired tags
        for tag in [no_supply_tag, no_demand_tag, stopping_vol_tag, selling_climax_tag, buying_climax_tag]:
            if tag is not None:
                tags.append(tag)
    
    return tags


def _check_no_supply(context: DailyContext) -> DailyTag | None:
    """No Supply: down day, narrow spread, low volume.
    
    Extremity measured as distance BELOW the threshold, not vs 1.0.
    This prevents a bar that just barely qualifies (pctile=0.29 vs threshold 0.30)
    from getting high strength (0.71), and reserves high strength for truly
    extreme readings (pctile=0.05).
    """
    if context.direction >= 0:
        return None
    
    if (context.spread_percentile < DAILY_LOW_SPREAD_PCTILE and
        context.volume_percentile < DAILY_LOW_VOL_PCTILE):
        
        # Extremity = how far BELOW the threshold (0.0 at threshold, 1.0 at zero percentile)
        spread_extremity = (DAILY_LOW_SPREAD_PCTILE - context.spread_percentile) / DAILY_LOW_SPREAD_PCTILE
        volume_extremity = (DAILY_LOW_VOL_PCTILE - context.volume_percentile) / DAILY_LOW_VOL_PCTILE
        
        composite_strength = (spread_extremity + volume_extremity) / 2
        composite_strength = min(1.0, max(0.0, composite_strength))
        
        tier = SignalTier.MAJOR_SIGNAL if composite_strength >= TIER_MAJOR_THRESHOLD else SignalTier.MINOR_OBSERVATION
        
        return DailyTag(
            code=EvidenceCode.NO_SUPPLY,
            date=context.date,
            bar_index=context.bar_index,
            tier=tier,
            strength=composite_strength,
            direction=-1,
        )
    
    return None


def _check_no_demand(context: DailyContext) -> DailyTag | None:
    """No Demand: up day, narrow spread, low volume.
    
    Extremity measured as distance BELOW the threshold (same as NO_SUPPLY).
    """
    if context.direction <= 0:
        return None
    
    if (context.spread_percentile < DAILY_LOW_SPREAD_PCTILE and
        context.volume_percentile < DAILY_LOW_VOL_PCTILE):
        
        # Extremity = how far BELOW the threshold
        spread_extremity = (DAILY_LOW_SPREAD_PCTILE - context.spread_percentile) / DAILY_LOW_SPREAD_PCTILE
        volume_extremity = (DAILY_LOW_VOL_PCTILE - context.volume_percentile) / DAILY_LOW_VOL_PCTILE
        
        composite_strength = (spread_extremity + volume_extremity) / 2
        composite_strength = min(1.0, max(0.0, composite_strength))
        
        tier = SignalTier.MAJOR_SIGNAL if composite_strength >= TIER_MAJOR_THRESHOLD else SignalTier.MINOR_OBSERVATION
        
        return DailyTag(
            code=EvidenceCode.NO_DEMAND,
            date=context.date,
            bar_index=context.bar_index,
            tier=tier,
            strength=composite_strength,
            direction=1,
        )
    
    return None


def _check_stopping_volume(context: DailyContext) -> DailyTag | None:
    """Stopping Volume: high volume, strong close (CLV > 0.65), after prior decline."""
    if (context.volume_percentile >= DAILY_HIGH_VOL_PCTILE and
        context.close_location_value >= DAILY_STRONG_CLV):
        
        composite_strength = (
            (context.volume_percentile - DAILY_HIGH_VOL_PCTILE) / (1 - DAILY_HIGH_VOL_PCTILE) +
            (context.close_location_value - DAILY_STRONG_CLV) / (1 - DAILY_STRONG_CLV)
        ) / 2
        composite_strength = min(1.0, max(0.0, composite_strength))
        
        tier = SignalTier.MAJOR_SIGNAL if composite_strength >= TIER_MAJOR_THRESHOLD else SignalTier.MINOR_OBSERVATION
        
        return DailyTag(
            code=EvidenceCode.STOPPING_VOLUME,
            date=context.date,
            bar_index=context.bar_index,
            tier=tier,
            strength=composite_strength,
            direction=1,
        )
    
    return None


def _check_selling_climax(context: DailyContext) -> DailyTag | None:
    """Selling Climax: high vol + high spread + low CLV (strong selling)."""
    if (context.volume_percentile >= DAILY_HIGH_VOL_PCTILE and
        context.spread_percentile >= DAILY_HIGH_SPREAD_PCTILE and
        context.close_location_value < DAILY_WEAK_CLV):
        
        vol_strength = (context.volume_percentile - DAILY_HIGH_VOL_PCTILE) / (1 - DAILY_HIGH_VOL_PCTILE)
        spread_strength = (context.spread_percentile - DAILY_HIGH_SPREAD_PCTILE) / (1 - DAILY_HIGH_SPREAD_PCTILE)
        clv_strength = (DAILY_WEAK_CLV - context.close_location_value) / DAILY_WEAK_CLV
        
        composite_strength = (vol_strength + spread_strength + clv_strength) / 3
        composite_strength = min(1.0, max(0.0, composite_strength))
        
        tier = SignalTier.MAJOR_SIGNAL if composite_strength >= TIER_MAJOR_THRESHOLD else SignalTier.MINOR_OBSERVATION
        
        return DailyTag(
            code=EvidenceCode.SELLING_CLIMAX,
            date=context.date,
            bar_index=context.bar_index,
            tier=tier,
            strength=composite_strength,
            direction=-1,
        )
    
    return None


def _check_buying_climax(context: DailyContext) -> DailyTag | None:
    """Buying Climax: high vol + high spread + CLV NOT strong (exhaustion)."""
    if (context.volume_percentile >= DAILY_HIGH_VOL_PCTILE and
        context.spread_percentile >= DAILY_HIGH_SPREAD_PCTILE and
        context.close_location_value < DAILY_STRONG_CLV and
        context.direction > 0):
        
        vol_strength = (context.volume_percentile - DAILY_HIGH_VOL_PCTILE) / (1 - DAILY_HIGH_VOL_PCTILE)
        spread_strength = (context.spread_percentile - DAILY_HIGH_SPREAD_PCTILE) / (1 - DAILY_HIGH_SPREAD_PCTILE)
        clv_weakness = (DAILY_STRONG_CLV - context.close_location_value) / DAILY_STRONG_CLV
        
        composite_strength = (vol_strength + spread_strength + clv_weakness) / 3
        composite_strength = min(1.0, max(0.0, composite_strength))
        
        tier = SignalTier.MAJOR_SIGNAL if composite_strength >= TIER_MAJOR_THRESHOLD else SignalTier.MINOR_OBSERVATION
        
        return DailyTag(
            code=EvidenceCode.BUYING_CLIMAX,
            date=context.date,
            bar_index=context.bar_index,
            tier=tier,
            strength=composite_strength,
            direction=1,
        )
    
    return None
