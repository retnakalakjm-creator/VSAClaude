"""
VSAClaude Configuration
Central place for all tunable parameters.
"""

# ============================================================================
# SWING ENGINE SETTINGS
# ============================================================================
SWING_REVERSAL_PERCENT = 3.0  # ZigZag reversal threshold (%)
SWING_MIN_BARS = 2             # Minimum bars between swings

# ============================================================================
# STRUCTURAL FILTERING SETTINGS
# ============================================================================
# A swing only becomes STRUCTURAL if it meets these criteria:
STRUCTURAL_MIN_PRICE_DISPLACEMENT = 1.5  # ATR-equivalent multiples
STRUCTURAL_MIN_DURATION = 3               # bars
STRUCTURAL_MIN_VOLUME_PERCENTILE = 0.40  # of trailing 20-bar average
STRUCTURAL_MIN_SPREAD_PERCENTILE = 0.35  # of trailing 20-bar average

# ============================================================================
# EVIDENCE SETTINGS
# ============================================================================
# Evidence must persist across this many qualifying bars to become actionable
EVIDENCE_MIN_PERSISTENCE = 3
EVIDENCE_PERSISTENCE_MIN_SPACING = 4  # bars between qualifying observations

# ============================================================================
# DAILY TAGGING SETTINGS
# ============================================================================
DAILY_LOOKBACK_WINDOW = 20  # trading days for rolling percentile
DAILY_HIGH_VOL_PCTILE = 0.85
DAILY_HIGH_SPREAD_PCTILE = 0.85
DAILY_LOW_VOL_PCTILE = 0.30
DAILY_LOW_SPREAD_PCTILE = 0.30
DAILY_STRONG_CLV = 0.65
DAILY_WEAK_CLV = 0.35

# ============================================================================
# TAG TIERING SETTINGS
# ============================================================================
# Composite strength score >= this threshold = MAJOR_SIGNAL
# Otherwise = MINOR_OBSERVATION (if fired) or NEUTRAL (if didn't fire)
# Tuned via historical diagnostic to achieve ~50% MAJOR_SIGNAL rate
TIER_MAJOR_THRESHOLD = 0.50

# ============================================================================
# TREND SETTINGS
# ============================================================================
TREND_PIVOT_TOLERANCE = 0.02  # 2% minimum gap between structural pivots
TREND_RECENT_SWINGS = 4        # recent swings to analyze for state/quality
TREND_STATE_MARGIN = 0.25      # margin between bullish/bearish dominance

# ============================================================================
# DATA & PROCESSING
# ============================================================================
DATA_DIR = "data"
CACHE_DIR = "cache"
OUTPUT_DIR = "output"
