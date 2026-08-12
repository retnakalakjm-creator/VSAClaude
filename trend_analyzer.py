"""
Trend Analyzer: classifies swings and determines trend.

From a sequence of structural swings, determines:
- HH/HL/LH/LL classification
- Trend direction (UP/DOWN/RANGE)
- Trend state (DEVELOPING/HEALTHY/CORRECTING/EXHAUSTED/REVERSING)
- Trend quality (strength, confidence)
"""

from typing import List, Tuple
from models import (
    StructuralSwing, SwingType, TrendResult, TrendDirection, TrendState,
    SwingClassification
)
from config import TREND_PIVOT_TOLERANCE, TREND_RECENT_SWINGS, TREND_STATE_MARGIN


def classify_swings(swings: List[StructuralSwing]) -> List[SwingClassification]:
    """
    Classify each swing relative to previous structural levels.
    HH = current high > previous high
    HL = current high < previous high (but is a high)
    LH = current low > previous low (but is a low)
    LL = current low < previous low
    """
    if len(swings) < 2:
        return []
    
    classifications: List[SwingClassification] = []
    prev_high: float | None = None
    prev_low: float | None = None
    
    for swing in swings:
        curr_price = swing.swing.price
        is_high = swing.swing.type == SwingType.HIGH
        
        if is_high:
            is_hh = prev_high is not None and curr_price > prev_high * (1 + TREND_PIVOT_TOLERANCE)
            is_hl = prev_high is not None and curr_price < prev_high * (1 - TREND_PIVOT_TOLERANCE)
            prev_high = curr_price
        else:  # swing is a low
            is_ll = prev_low is not None and curr_price < prev_low * (1 - TREND_PIVOT_TOLERANCE)
            is_lh = prev_low is not None and curr_price > prev_low * (1 + TREND_PIVOT_TOLERANCE)
            prev_low = curr_price
        
        if is_high:
            classification = SwingClassification(
                current_swing=swing,
                previous_high=prev_high,
                previous_low=prev_low,
                is_higher_high=is_hh,
                is_higher_low=False,
                is_lower_high=is_hl,
                is_lower_low=False,
            )
        else:
            classification = SwingClassification(
                current_swing=swing,
                previous_high=prev_high,
                previous_low=prev_low,
                is_higher_high=False,
                is_higher_low=is_lh,
                is_lower_high=False,
                is_lower_low=is_ll,
            )
        
        classifications.append(classification)
    
    return classifications


def analyze_trend(swings: List[StructuralSwing]) -> TrendResult:
    """
    Determine trend direction, state, and quality from swing sequence.
    
    Uses RECENT_SWINGS most recent swings weighted by recency (newest = strongest).
    """
    if not swings:
        return TrendResult(
            direction=TrendDirection.RANGE,
            state=TrendState.DEVELOPING,
            strength=0.0,
            confidence=0.0,
            swing_count=0,
            bullish_swings=0,
            bearish_swings=0,
            swings=(),
        )
    
    classifications = classify_swings(swings)
    if not classifications:
        return TrendResult(
            direction=TrendDirection.RANGE,
            state=TrendState.DEVELOPING,
            strength=0.0,
            confidence=0.0,
            swing_count=len(swings),
            bullish_swings=0,
            bearish_swings=0,
            swings=tuple(swings),
        )
    
    # Use most recent N swings for direction determination
    recent_count = min(TREND_RECENT_SWINGS, len(classifications))
    recent = classifications[-recent_count:]
    
    bullish_count = sum(1 for c in recent if c.is_higher_high or c.is_higher_low)
    bearish_count = sum(1 for c in recent if c.is_lower_high or c.is_lower_low)
    
    # Weighted dominance: newest swings weighted heaviest
    bullish_weight = sum(
        (i + 1) for i, c in enumerate(recent) if c.is_higher_high or c.is_higher_low
    )
    bearish_weight = sum(
        (i + 1) for i, c in enumerate(recent) if c.is_lower_high or c.is_lower_low
    )
    
    total_weight = bullish_weight + bearish_weight
    if total_weight == 0:
        dominance = 0.0
    else:
        dominance = (bullish_weight - bearish_weight) / total_weight
    
    # Determine direction based on dominance margin
    if dominance > TREND_STATE_MARGIN:
        direction = TrendDirection.UP
    elif dominance < -TREND_STATE_MARGIN:
        direction = TrendDirection.DOWN
    else:
        direction = TrendDirection.RANGE
    
    # Determine state from pattern of recent swings
    state = _determine_state(recent, direction)
    
    # Quality metrics
    strength = abs(dominance)
    confidence = min(1.0, bullish_count / TREND_RECENT_SWINGS if direction == TrendDirection.UP
                         else bearish_count / TREND_RECENT_SWINGS if direction == TrendDirection.DOWN
                         else 0.5)
    
    return TrendResult(
        direction=direction,
        state=state,
        strength=strength,
        confidence=confidence,
        swing_count=len(swings),
        bullish_swings=bullish_count,
        bearish_swings=bearish_count,
        swings=tuple(swings),
    )


def _determine_state(recent_classifications: List[SwingClassification],
                     direction: TrendDirection) -> TrendState:
    """
    Determine trend state (lifecycle) from the pattern of recent swings.
    
    HEALTHY: aligned swings in the direction
    DEVELOPING: new trend starting
    CORRECTING: pullback/retracement
    EXHAUSTED: momentum slowing but structure intact
    REVERSING: structure breaking down
    """
    if len(recent_classifications) < 2:
        return TrendState.DEVELOPING
    
    last = recent_classifications[-1]
    prev = recent_classifications[-2] if len(recent_classifications) > 1 else None
    
    if direction == TrendDirection.UP:
        if last.is_higher_high or last.is_higher_low:
            if last.is_higher_high:
                return TrendState.HEALTHY
            else:
                return TrendState.CORRECTING
        else:
            return TrendState.EXHAUSTED
    
    elif direction == TrendDirection.DOWN:
        if last.is_lower_low or last.is_lower_high:
            if last.is_lower_low:
                return TrendState.HEALTHY
            else:
                return TrendState.CORRECTING
        else:
            return TrendState.EXHAUSTED
    
    else:  # RANGE
        # In a range, alternating highs and lows suggest consolidation
        return TrendState.DEVELOPING
