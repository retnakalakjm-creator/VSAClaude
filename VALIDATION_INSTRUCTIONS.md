# VSAClaude Validation: Historical Data Testing

Now that the foundation is committed, we validate it against real historical data.

## What We're Testing

1. **Swing Detection Sanity**
   - Are swings being found? (not 0, not 10000)
   - Is the filter effectively removing noise? (raw → structural ratio)

2. **Structural Filtering Effectiveness**
   - What % of raw swings survive the structural filter?
   - (Goal: ~10-30%, depends on stock volatility)

3. **Crash Detection**
   - 2008 Financial Crisis (Jan-Nov 2008)
   - 2020 COVID Crash (Feb-Apr 2020)
   - Did the system detect downtrends during these periods?

4. **Daily Tag Distribution**
   - Are daily signals firing too much, too little, or just right?
   - MAJOR_SIGNAL / MINOR_OBSERVATION split

5. **Trend Classification**
   - Direction (UP/DOWN/RANGE)
   - State (DEVELOPING/HEALTHY/CORRECTING/EXHAUSTED/REVERSING)

## Files Provided

- `data_loader.py` — Load NSE OHLCV CSV files
- `validate.py` — Run the full pipeline on historical data and report diagnostics

## How to Run

**Prerequisites:**
- Your VSAClaude repo with the foundation committed
- Your NSE historical data (same 18 stocks from VSAScanner)

**Step 1: Place your data**

Copy your CSV files into a `stocks/` directory at the repo root:
```
VSAClaude/
├── config.py
├── models.py
├── swing_engine.py
├── ...
└── stocks/
    ├── HDFCBANK.csv
    ├── RELIANCE.csv
    ├── TATASTEEL.csv
    ├── TITAN.csv
    ├── DLF.csv
    └── ... (other stocks)
```

Each CSV should have columns: `date,open,high,low,close,volume`

**Step 2: Add data_loader.py and validate.py to repo**

Copy the two new files to your VSAClaude root.

**Step 3: Run validation**

```bash
# Validate the 5 key tickers
python validate.py --data-dir stocks/ --tickers HDFCBANK RELIANCE TATASTEEL TITAN DLF

# Or validate all stocks in the directory
python validate.py --data-dir stocks/ --all

# Verbose mode (detailed output)
python validate.py --data-dir stocks/ --tickers HDFCBANK --verbose
```

## Expected Output

```
VSACLAUDE HISTORICAL VALIDATION REPORT
====================================================================================================

TICKER: HDFCBANK
  Data range: 1996-01-01 to 2026-08-10 (7742 bars)
  Raw swings: 1247 → Structural: 145 (filter rate: 11.6%)
  Trend: UP (HEALTHY) strength=78% confidence=85%
  Swings: 8 bullish, 2 bearish
  Daily tags: 342 total (187 major, 155 minor) — 54.7% are MAJOR_SIGNAL
  Regime segments: 47
  ✓ DETECTED 2008 Financial Crisis: 2 downtrend segment(s)
  ✓ DETECTED 2020 COVID Crash: 1 downtrend segment(s)

[similar output for other tickers...]

SUMMARY
====================================================================================================
Average swing filter rate: 13.2%
Average MAJOR_SIGNAL rate: 52.3%
Crash detection: 10/10 windows detected
```

## What These Metrics Mean

### Swing Filter Rate
- **10-20%** is healthy (most pivots are noise)
- **< 5%** means filter is too strict
- **> 40%** means filter is too loose

### Daily Tag Distribution
- **MAJOR_SIGNAL rate < 30%** — signals are rare, may miss opportunities
- **MAJOR_SIGNAL rate 40-60%** — healthy balance
- **MAJOR_SIGNAL rate > 70%** — too many signals, noise problem

### Crash Detection
- Should detect both 2008 and 2020 on every stock
- If missing on certain stocks → investigate why (volatility, early data issues, etc.)

## Next Steps After Validation

1. **If validation passes** (crash detection ✓, metrics reasonable):
   - Commit validation files to repo
   - Proceed to evidence persistence tracking (campaigns across multiple bars)
   - Build the narrative synthesis layer

2. **If validation finds issues**:
   - Adjust thresholds in `config.py`
   - Re-run validation
   - Iterate until metrics look good

3. **If crash detection fails on some stocks**:
   - Check data quality for that stock (missing bars, data errors)
   - Consider per-stock tuning of STRUCTURAL_MIN_* thresholds
   - Investigate whether the crash was visible in that stock's data

## Questions?

Check the docstrings in `data_loader.py` and `validate.py` for detailed parameter descriptions.
