# VSAClaude Calibration Recommendation

## Diagnostic Results (HDFCBANK.NS)

### Total Daily Tags: 2321
- NO_SUPPLY: 624 instances (8.12% of bars) — strength 0.827 mean
- NO_DEMAND: 757 instances (9.85% of bars) — strength 0.839 mean
- SELLING_CLIMAX: 314 instances (4.09% of bars) — strength 0.687 mean
- STOPPING_VOLUME: 498 instances (6.48% of bars) — strength 0.468 mean
- BUYING_CLIMAX: 128 instances (1.67% of bars) — strength 0.475 mean

### Current Status (threshold=0.40)
- **MAJOR_SIGNAL count: 2000 (86.2%)**
- **Target: 40-60% MAJOR_SIGNAL**
- Status: **TOO AGGRESSIVE** ❌

---

## Root Cause Analysis

The diagnostic shows a clear problem: **NO_SUPPLY and NO_DEMAND are inherently strong signals** (mean strength 0.83+), so they fire as MAJOR at virtually any threshold.

At threshold 0.70 (maximum reasonable), they're STILL 100% MAJOR.

This means the extremity calculation for these signals is **too generous**. When a bar shows low volume AND low spread, we're computing full extremity (1.0) for both, which pushes the composite to ~0.83. That's mathematically correct but practically wrong — NO_SUPPLY/DEMAND shouldn't be "extreme" just because they meet the basic criteria.

---

## Solution: Two-Tier Approach

### Step 1: Adjust NO_SUPPLY / NO_DEMAND Extremity (RECOMMENDED)

The problem is in `daily_tagger.py` — we're treating "meets the threshold" as "maximum strength."

**Current logic (wrong):**
```python
spread_strength = 1.0 - context.spread_percentile  # If pctile=0.20, strength=0.80
volume_strength = 1.0 - context.volume_percentile  # If pctile=0.25, strength=0.75
composite = (spread_strength + volume_strength) / 2 = 0.775 → Always MAJOR at 0.40
```

**Better logic:**
```python
# Only consider the PORTION PAST the threshold a sign of strength
spread_extremity = max(0, (0.30 - context.spread_percentile) / 0.30)  # 0.0-1.0 scale within "low" range
volume_extremity = max(0, (0.40 - context.volume_percentile) / 0.40)
composite = (spread_extremity + volume_extremity) / 2  # Now in 0.0-0.5 range typically
```

This way, a bar with pctile=0.29 (just barely under threshold) gets 0.03 strength, while one with pctile=0.05 gets 0.83 strength.

### Step 2: Set Threshold to 0.50

After applying Step 1, set:
```python
TIER_MAJOR_THRESHOLD = 0.50
```

This should give you roughly 50% MAJOR_SIGNAL across the board.

---

## Implementation

Edit `daily_tagger.py`:

**Find this function:**
```python
def _check_no_supply(context: DailyContext) -> DailyTag | None:
    if context.direction >= 0:
        return None
    
    spread_strength = 1.0 - context.spread_percentile  # ← CHANGE THIS
    volume_strength = 1.0 - context.volume_percentile  # ← CHANGE THIS
```

**Replace with:**
```python
def _check_no_supply(context: DailyContext) -> DailyTag | None:
    if context.direction >= 0:
        return None
    
    # Only count extremity BELOW the threshold (not vs. 1.0)
    if context.spread_percentile < DAILY_LOW_SPREAD_PCTILE:
        spread_extremity = (DAILY_LOW_SPREAD_PCTILE - context.spread_percentile) / DAILY_LOW_SPREAD_PCTILE
    else:
        spread_extremity = 0.0
    
    if context.volume_percentile < DAILY_LOW_VOL_PCTILE:
        volume_extremity = (DAILY_LOW_VOL_PCTILE - context.volume_percentile) / DAILY_LOW_VOL_PCTILE
    else:
        volume_extremity = 0.0
```

Do the same for `_check_no_demand`.

Then update `config.py`:
```python
TIER_MAJOR_THRESHOLD = 0.50  # was 0.40
```

---

## Expected Result After Fix

```
NO_SUPPLY:  mean strength 0.40-0.45 (down from 0.83)
NO_DEMAND:  mean strength 0.42-0.47 (down from 0.84)
SELLING_CLIMAX: mean unchanged (~0.69)
STOPPING_VOLUME: mean unchanged (~0.47)

Total MAJOR_SIGNAL: ~50% (target range: 40-60%)
```

---

## How to Validate

After making the changes:

1. Run diagnostic again:
   ```bash
   python diagnose.py --data-dir stocks/ --ticker HDFCBANK
   ```

2. Check that NO_SUPPLY/NO_DEMAND strength dropped to 0.40-0.50 range

3. Re-run full validation:
   ```bash
   python validate.py --data-dir stocks/ --tickers HDFCBANK RELIANCE TATASTEEL TITAN DLF
   ```

4. Confirm MAJOR_SIGNAL rate is now 40-60%

---

## File Updates Needed

1. `data_loader.py` — Already updated to handle `.NS` suffix ✓
2. `daily_tagger.py` — Update NO_SUPPLY/NO_DEMAND extremity calculations
3. `config.py` — Change TIER_MAJOR_THRESHOLD from 0.40 to 0.50
