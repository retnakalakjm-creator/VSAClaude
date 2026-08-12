"""
Swing Engine: ZigZag-based pivot detection.

Replaces Break-of-Structure method with a cleaner reversal-threshold approach.
Avoids the staleness problem where ancient price levels control modern analysis.
"""

from typing import List, Tuple
import pandas as pd
import numpy as np

from models import Swing, SwingType, SwingGrade
from config import SWING_REVERSAL_PERCENT, SWING_MIN_BARS


def detect_swings(df: pd.DataFrame) -> List[Swing]:
    """
    Detect swings using ZigZag reversal threshold method.
    
    A swing high is formed when price rises REVERSAL_PERCENT from the
    running low. A swing low is formed when price falls REVERSAL_PERCENT
    from the running high. This avoids reference-level staleness by only
    comparing to the CURRENT running extreme, not an ancient historical level.
    
    Args:
        df: DataFrame with OHLCV columns and 'date' index
    
    Returns:
        List of confirmed Swing objects in chronological order
    """
    if len(df) < SWING_MIN_BARS:
        return []
    
    swings: List[Swing] = []
    
    # Initialize tracking
    running_high = df['high'].iloc[0]
    running_low = df['low'].iloc[0]
    last_swing_type: SwingType | None = None
    last_swing_price: float | None = None
    last_swing_index: int = 0
    
    reversal_threshold = SWING_REVERSAL_PERCENT / 100.0
    
    for i in range(1, len(df)):
        current_high = df['high'].iloc[i]
        current_low = df['low'].iloc[i]
        current_date = df.index[i]
        
        # Track running extremes
        running_high = max(running_high, current_high)
        running_low = min(running_low, current_low)
        
        # Check for swing high: price falls from running high
        if last_swing_type != SwingType.HIGH:
            if running_high > 0 and current_low < running_high * (1 - reversal_threshold):
                # Confirmed swing high at the running high
                if running_high != (last_swing_price or 0) or i - last_swing_index >= SWING_MIN_BARS:
                    swing = Swing(
                        bar_index=i - 1 if i > 0 else 0,  # swing occurred before reversal
                        date=current_date,
                        price=running_high,
                        type=SwingType.HIGH,
                        grade=_grade_swing(running_high, running_low),
                    )
                    swings.append(swing)
                    last_swing_type = SwingType.HIGH
                    last_swing_price = running_high
                    last_swing_index = i
                    running_low = current_low
        
        # Check for swing low: price rises from running low
        if last_swing_type != SwingType.LOW:
            if running_low > 0 and current_high > running_low * (1 + reversal_threshold):
                # Confirmed swing low at the running low
                if running_low != (last_swing_price or 0) or i - last_swing_index >= SWING_MIN_BARS:
                    swing = Swing(
                        bar_index=i - 1 if i > 0 else 0,
                        date=current_date,
                        price=running_low,
                        type=SwingType.LOW,
                        grade=_grade_swing(running_high, running_low),
                    )
                    swings.append(swing)
                    last_swing_type = SwingType.LOW
                    last_swing_price = running_low
                    last_swing_index = i
                    running_high = current_high
    
    return swings


def _grade_swing(high: float, low: float, base_reference: float | None = None) -> SwingGrade:
    """
    Simple grading based on amplitude of the swing.
    Range of 0-3% = MINOR, 3-8% = STANDARD, 8-15% = MAJOR, 15%+ = INSTITUTIONAL
    """
    if high <= 0 or low <= 0:
        return SwingGrade.STANDARD
    
    amplitude_pct = ((high - low) / low) * 100
    
    if amplitude_pct >= 15:
        return SwingGrade.INSTITUTIONAL
    elif amplitude_pct >= 8:
        return SwingGrade.MAJOR
    elif amplitude_pct >= 3:
        return SwingGrade.STANDARD
    else:
        return SwingGrade.MINOR
