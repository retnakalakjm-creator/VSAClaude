# VSAClaude

A clean, modular VSA/Wyckoff pattern analyzer for Indian equities (NSE).

## Architecture

```
WEEKLY OHLCV
    ↓
SWING ENGINE (swing_engine.py)
  • ZigZag reversal-threshold detection
  • Avoids staleness from old price levels
    ↓
STRUCTURE FILTER (structure_filter.py)
  • Filters by: displacement, duration, volume, spread
  • Only structurally significant swings proceed
    ↓
TREND ANALYZER (trend_analyzer.py)
  • Classify swings: HH, HL, LH, LL
  • Determine: direction (UP/DOWN/RANGE)
  • Determine: state (DEVELOPING/HEALTHY/CORRECTING/EXHAUSTED/REVERSING)
  • Score: strength, confidence
    ↓
DAILY TAGGER (daily_tagger.py)
  • Detect bar patterns:
    - No Supply / No Demand
    - Stopping Volume
    - Selling / Buying Climax
  • Tier each signal: MAJOR_SIGNAL / MINOR_OBSERVATION / NEUTRAL
    ↓
SCAN RESULT (models.py)
  • Complete analysis: swings, trend, daily signals
```

## Design Principles

1. **ZigZag over Break-of-Structure**: Compares current price to *running* extremes, not ancient references. Avoids the staleness bug where 30-year-old levels still "control" modern price action.

2. **Structural Filtering as a Distinct Stage**: Not every pivot matters. We explicitly filter by price displacement, duration, and volume/spread strength before trend analysis.

3. **Persistent Evidence**: Signals must prove themselves across multiple bars, not fire on single-bar noise.

4. **Three-Tier Confidence**: MAJOR_SIGNAL / MINOR_OBSERVATION / NEUTRAL — calibrated to how convincingly each pattern meets its thresholds.

5. **Trend Lifecycle**: Five states (not just up/down/range) — DEVELOPING, HEALTHY, CORRECTING, EXHAUSTED, REVERSING.

## Configuration

All tunable parameters live in `config.py`:

- `SWING_REVERSAL_PERCENT`: ZigZag threshold (default 3%)
- `STRUCTURAL_MIN_PRICE_DISPLACEMENT`: ATR-equivalent multiples required
- `STRUCTURAL_MIN_VOLUME_PERCENTILE` / `STRUCTURAL_MIN_SPREAD_PERCENTILE`: strength filters
- `TIER_MAJOR_THRESHOLD`: signal confidence cutoff (default 0.40)
- `TREND_*`: trend analysis tuning

## Usage

```bash
python main.py HDFCBANK data/HDFCBANK.csv
```

Output:
```
SCAN RESULT: HDFCBANK as of 2026-08-10
======================================================================

STRUCTURAL SWINGS: 47 confirmed
  Direction: UP
  State: HEALTHY
  Strength: 78%
  Confidence: 85%
  Bullish swings: 6
  Bearish swings: 2

DAILY SIGNALS: 23 tags
    2026-08-08: NO_DEMAND                       MAJOR_SIGNAL      (strength=0.68)
    2026-08-09: STOPPING_VOLUME                 MINOR_OBSERVATION (strength=0.42)
    2026-08-10: NO_SUPPLY                       MAJOR_SIGNAL      (strength=0.72)
```

## Files

- `config.py` - All tunable parameters
- `models.py` - Core data structures and enums
- `swing_engine.py` - ZigZag swing detection
- `structure_filter.py` - Structural significance filtering
- `trend_analyzer.py` - Trend classification and analysis
- `daily_tagger.py` - Daily bar pattern detection with tiering
- `main.py` - Pipeline orchestrator
- `__init__.py` - Package marker

## Next Steps

- [ ] Evidence aggregation layer (track patterns across bars)
- [ ] Wyckoff phase classification
- [ ] Professional/institutional behavior scoring
- [ ] Full pipeline end-to-end validation on 5+ tickers
- [ ] Narrative synthesis (weekly story + daily trigger → actionable signal)
