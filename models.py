"""
VSAClaude Core Models

Data structures and enums representing swings, evidence, trends, and signals.
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional, Tuple
import pandas as pd


# ============================================================================
# ENUMS
# ============================================================================

class SwingType(Enum):
    """Type of swing: high or low."""
    HIGH = "high"
    LOW = "low"


class SwingGrade(Enum):
    """Structural significance of a confirmed swing."""
    MINOR = "minor"
    STANDARD = "standard"
    MAJOR = "major"
    INSTITUTIONAL = "institutional"


class SignalTier(Enum):
    """Confidence tier for a fired tag/evidence."""
    NEUTRAL = "neutral"
    MINOR_OBSERVATION = "minor_observation"
    MAJOR_SIGNAL = "major_signal"


class TrendDirection(Enum):
    """Direction of the trend."""
    DOWN = -1
    RANGE = 0
    UP = 1


class TrendState(Enum):
    """Health/lifecycle state of a trend."""
    DEVELOPING = "developing"
    HEALTHY = "healthy"
    CORRECTING = "correcting"
    EXHAUSTED = "exhausted"
    REVERSING = "reversing"


class EvidenceCode(Enum):
    """Evidence types: what structural patterns we detect."""
    NO_SUPPLY = "no_supply"
    NO_DEMAND = "no_demand"
    STOPPING_VOLUME = "stopping_volume"
    SELLING_CLIMAX = "selling_climax"
    BUYING_CLIMAX = "buying_climax"
    SPRING = "spring"
    UPTHRUST = "upthrust"
    ABSORPTION = "absorption"
    STRUCTURAL_PROGRESSION_IMPROVING = "structural_progression_improving"
    STRUCTURAL_PROGRESSION_WEAKENING = "structural_progression_weakening"


# ============================================================================
# SWING & STRUCTURE
# ============================================================================

@dataclass(frozen=True)
class Swing:
    """A confirmed pivot point (high or low) in price."""
    bar_index: int
    date: datetime
    price: float
    type: SwingType
    grade: SwingGrade = SwingGrade.STANDARD
    score: float = 0.0  # structural significance score


@dataclass(frozen=True)
class StructuralSwing:
    """A swing that meets structural importance thresholds."""
    swing: Swing
    displacement: float  # how far price moved from previous swing
    duration: int       # bars since previous swing
    volume_strength: float  # percentile of volume
    spread_strength: float  # percentile of spread


@dataclass(frozen=True)
class SwingClassification:
    """Classification of consecutive swings: HH, HL, LH, LL."""
    current_swing: StructuralSwing
    previous_high: Optional[float]
    previous_low: Optional[float]
    is_higher_high: bool
    is_higher_low: bool
    is_lower_high: bool
    is_lower_low: bool


# ============================================================================
# EVIDENCE & SIGNALS
# ============================================================================

@dataclass(frozen=True)
class Evidence:
    """A single detected structural pattern or signal."""
    code: EvidenceCode
    bar_index: int
    date: datetime
    strength: float  # 0.0-1.0
    direction: int   # -1 (bearish), 0 (neutral), +1 (bullish)
    quality: float   # 0.0-1.0, how well it fits the pattern


@dataclass(frozen=True)
class EvidenceCampaign:
    """Persistent tracking of an evidence type across qualifying bars."""
    code: EvidenceCode
    qualifying_bar_indices: Tuple[int, ...]  # chronological
    qualifying_dates: Tuple[datetime, ...]
    direction: int  # net direction of the campaign
    is_actionable: bool
    reason: str


# ============================================================================
# TREND & BACKGROUND
# ============================================================================

@dataclass(frozen=True)
class TrendResult:
    """Summary of current trend: direction, state, quality."""
    direction: TrendDirection
    state: TrendState
    strength: float       # 0.0-1.0
    confidence: float     # 0.0-1.0
    swing_count: int
    bullish_swings: int   # HH + HL
    bearish_swings: int   # LH + LL
    swings: Tuple[StructuralSwing, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StructuralBackground:
    """Weekly market context: what smart money is doing."""
    evidence_list: Tuple[Evidence, ...] = field(default_factory=tuple)
    campaigns: Tuple[EvidenceCampaign, ...] = field(default_factory=tuple)
    bullish_strength: float = 0.0
    bearish_strength: float = 0.0
    net_pressure: float = 0.0


# ============================================================================
# DAILY SIGNALS
# ============================================================================

@dataclass(frozen=True)
class DailyTag:
    """A daily bar pattern tag with confidence tier."""
    code: EvidenceCode
    date: datetime
    bar_index: int
    tier: SignalTier
    strength: float  # 0.0-1.0, how convincingly it fired
    direction: int   # -1, 0, or +1


@dataclass(frozen=True)
class DailyContext:
    """Daily bar data enriched with metrics."""
    date: datetime
    bar_index: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float
    close_location_value: float  # (close - low) / (high - low)
    volume_percentile: float
    spread_percentile: float
    direction: int  # -1 (down), 0 (doji), +1 (up)


# ============================================================================
# COMPOSITE RESULTS
# ============================================================================

@dataclass(frozen=True)
class ScanResult:
    """Complete analysis for a stock at a point in time."""
    symbol: str
    as_of_date: datetime
    
    # Structure
    swings: Tuple[StructuralSwing, ...]
    
    # Background (weekly)
    background: StructuralBackground
    trend: TrendResult
    
    # Signals (daily)
    daily_tags: Tuple[DailyTag, ...] = field(default_factory=tuple)
    
    # Top-down narrative
    weekly_story: str = ""
    daily_opportunity: str = ""
    confidence: float = 0.0
