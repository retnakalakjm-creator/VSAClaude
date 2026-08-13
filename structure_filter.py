"""
Structure Filter: filters raw swings by importance.

Not every pivot matters. This module ensures only structurally significant
swings participate in trend and evidence analysis.
"""

from typing import List
import pandas as pd
import numpy as np

from models import Swing, StructuralSwing, SwingType
from config import (
    STRUCTURAL_MIN_PRICE_DISPLACEMENT,
    STRUCTURAL_MIN_DURATION,
    STRUCTURAL_MIN_VOLUME_PERCENTILE,
    STRUCTURAL_MIN_SPREAD_PERCENTILE,
)


def filter_structural_swings(df: pd.DataFrame, swings: List[Swing]) -> List[StructuralSwing]:
    """
    Filter swings by structural importance criteria:
    - Price displacement from prior swing
    - Duration since prior swing
    - Volume strength
    - Spread strength
    
    Args:
        df: OHLCV DataFrame
        swings: List of raw Swing objects
    
    Returns:
        List of StructuralSwing objects that meet importance thresholds
    """
    if len(swings) < 2:
        return []
    
    # Compute metrics
    volume_ma = df['volume'].rolling(window=20, min_periods=5).mean()
    spread = df['high'] - df['low']
    spread_ma = spread.rolling(window=20, min_periods=5).mean()
    
    # Percentile ranks
    volume_pctile = df['volume'].rolling(window=20, min_periods=5).apply(
        lambda x: (x.iloc[-1] <= x).sum() / len(x), raw=False
    )
    spread_pctile = spread.rolling(window=20, min_periods=5).apply(
        lambda x: (x.iloc[-1] <= x).sum() / len(x), raw=False
    )
    
    structural_swings: List[StructuralSwing] = []
    
    for i in range(1, len(swings)):
        curr = swings[i]
        prev = swings[i - 1]
        
        # Displacement check
        if prev.price <= 0:
            continue
        displacement = abs(curr.price - prev.price) / prev.price
        atr_equiv = spread_ma.iloc[curr.bar_index] if curr.bar_index < len(spread_ma) else 0
        if atr_equiv <= 0:
            atr_equiv = 1.0
        displacement_atr = displacement / (atr_equiv / prev.price) if atr_equiv > 0 else 0
        
        if displacement_atr < STRUCTURAL_MIN_PRICE_DISPLACEMENT:
            continue
        
        # Duration check
        duration = curr.bar_index - prev.bar_index
        if duration < STRUCTURAL_MIN_DURATION:
            continue
        
        # Volume and spread strength checks
        if curr.bar_index >= len(volume_pctile):
            vol_strength = 0.0
        else:
            vol_strength = volume_pctile.iloc[curr.bar_index] or 0.0
        
        if curr.bar_index >= len(spread_pctile):
            spread_strength = 0.0
        else:
            spread_strength = spread_pctile.iloc[curr.bar_index] or 0.0
        
        # At least ONE of volume or spread should show strength
        # (we don't require BOTH, as they're independent measurements)
        strength_requirement = max(vol_strength, spread_strength) >= min(
            STRUCTURAL_MIN_VOLUME_PERCENTILE, STRUCTURAL_MIN_SPREAD_PERCENTILE
        )
        
        # For now, we're lenient on the volume/spread requirement during
        # early history when percentiles haven't stabilized yet
        if curr.bar_index < 50:
            strength_requirement = True
        
        if not strength_requirement:
            continue
        
        # This swing passed all checks
        structural = StructuralSwing(
            swing=curr,
            displacement=displacement_atr,
            duration=duration,
            volume_strength=vol_strength,
            spread_strength=spread_strength,
        )
        structural_swings.append(structural)
    
    return structural_swings
