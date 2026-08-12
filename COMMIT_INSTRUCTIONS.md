# VSAClaude - Initial Commit Instructions

This is the clean foundation for VSAClaude, built from lessons learned in VSAScanner and insights from ProVSA.

## Files Included

### Core Modules
- `config.py` — All tunable parameters (one place to adjust behavior)
- `models.py` — Data structures and enums (Swing, Evidence, TrendResult, etc.)
- `swing_engine.py` — ZigZag-based swing detection (avoids staleness)
- `structure_filter.py` — Filters swings by importance
- `trend_analyzer.py` — Classifies swings, determines trend direction/state
- `daily_tagger.py` — Detects daily bar patterns with Major/Minor/Neutral tiering
- `main.py` — Orchestrator that runs the complete pipeline

### Project Files
- `__init__.py` — Package marker
- `README.md` — Architecture overview and usage guide
- `requirements.txt` — Python dependencies (pandas, numpy)
- `.gitignore` — Standard Python gitignore

## How to Commit

1. **Navigate to your VSAClaude repo:**
   ```bash
   cd /path/to/VSAClaude
   ```

2. **Copy all files from the download:**
   - Copy all `.py` files
   - Copy `README.md`
   - Copy `requirements.txt`
   - Copy `.gitignore`

3. **Stage and commit:**
   ```bash
   git add .
   git commit -m "Initial foundation: ZigZag swings, structure filtering, trend analysis, daily tagging"
   git push origin main
   ```

## Architecture Highlights

### Why ZigZag?
The old Break-of-Structure method had a critical flaw: ancient price levels (like Rs 8 from 1996) could permanently control analysis of modern price (Rs 700+). ZigZag avoids this by comparing only to *current* running extremes, not historical references.

### Why Structural Filtering?
Not every pivot matters. Before a swing enters trend analysis, it must prove:
- Minimum price displacement from the prior swing
- Minimum duration (not every bar-to-bar wiggle)
- Volume and spread strength (genuine activity, not noise)

### Why Three-Tier Signals?
Raw True/False tags throw away information. A `NO_SUPPLY` that barely scrapes the threshold (vol_pctile=0.31 vs threshold 0.30) is real but different from vol_pctile=0.95. Our tiers reflect this:
- `MAJOR_SIGNAL` — evidence sits well past its threshold
- `MINOR_OBSERVATION` — fired, but marginal
- `NEUTRAL` — didn't fire

### Why Five-State Trends?
Direction alone (UP/DOWN/RANGE) isn't enough. Trend state (DEVELOPING/HEALTHY/CORRECTING/EXHAUSTED/REVERSING) tells you where a trend is in its lifecycle.

## What's Not Yet Implemented

This is a foundation. Still needed:
- Evidence aggregation (track patterns across multiple bars as "campaigns")
- Wyckoff phase classification
- Professional/institutional behavior scoring
- Full end-to-end validation on real historical data
- Narrative synthesis (weekly story + daily trigger → signal)

These are deliberate deferments to keep the first commit clean and focused.

## Next Session Plan

1. **Validate against historical data** — run against 5+ NSE stocks across 2008 crash, 2020 COVID crash, and normal periods
2. **Add evidence persistence tracking** — patterns should persist across bars before becoming actionable
3. **Build the narrative layer** — weekly background + daily trigger → confidence-scored opportunity
4. **Integrate with ProVSA insights** — ProVSA's 5-state swing persistence model has lessons we should incorporate

## Questions?

See `README.md` for architecture overview and usage examples.
