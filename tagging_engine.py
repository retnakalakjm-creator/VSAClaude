"""
STEP 4: MULTI-BAR REACTION AND STRUCTURAL STATE ASSIGNMENT ENGINE
-----------------------------------------------------------------
Goal: Assign a focused first set of 10 structural tags (spanning
Supply, Demand, Wyckoff Events, Trend Basics, and Effort-vs-Result)
onto the weekly Z-score/CLV data from Step 3.

We deliberately start with 10 well-separated tags instead of all 45,
so each one's logic can be individually audited before we scale up.

THRESHOLDS (tunable constants, all defined at the top):
  - HIGH_VOL_Z / HIGH_SPREAD_Z: what counts as an unusually high
    volume/spread week for THIS stock's own recent volatility footprint
  - LOW_VOL_Z / LOW_SPREAD_Z: what counts as an unusually quiet week
  - WEAK_CLV / STRONG_CLV: what counts as closing near the low / high
  - CONTEXT_LOOKBACK: how many prior weeks define "trend context"
    (used for climaxes, no-supply/no-demand, stopping volume)
  - RANGE_LOOKBACK: how many prior weeks define the range high/low
    used for Spring / Upthrust detection
  - CONFIRM_FORWARD: how many future weeks must hold for a
    Spring/Upthrust to count as "confirmed" rather than "pending"

All windows use pandas .shift() so index i only ever looks at bars
strictly BEFORE or AFTER i, never leaking i's own value into its own
context calculation.

Depends on Step 1-3 and does not modify them.
"""

import pandas as pd
import numpy as np
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe
from weekly_metrics import build_weekly_dataset

# ---- Tunable thresholds -----------------------------------------------
# PRIMARY normalization is now rolling PERCENTILE RANK (0.0-1.0), not Z-score.
# Chosen over Z-score because volume/spread are right-skewed, not normal,
# and percentile rank is far more robust to a single outlier bar distorting
# the whole rolling window (a Z-score's mean/std gets dragged around by one
# freak bar; a percentile rank just ranks it #1 and moves on cleanly).
HIGH_VOL_PCTILE = 0.85     # top 15% of volume within the trailing 20 weeks
HIGH_SPREAD_PCTILE = 0.85   # top 15% of spread within the trailing 20 weeks
LOW_VOL_PCTILE = 0.30        # bottom 30% of volume within the trailing 20 weeks
LOW_SPREAD_PCTILE = 0.30      # bottom 30% of spread within the trailing 20 weeks
WEAK_CLV = 0.35        # close in bottom 35% of the bar's range
STRONG_CLV = 0.65       # close in top 35% of the bar's range

# Z-score is kept ONLY as a secondary, magnitude-sensitive feature for
# calculations that need spread and volume compared on one continuous
# numeric scale -- currently just ABSORPTION below.
HIGH_VOL_Z = 1.5
HIGH_SPREAD_Z = 1.5
CONTEXT_LOOKBACK = 8     # weeks of prior context for climax/no-supply/no-demand
RANGE_LOOKBACK = 12       # weeks defining the range high/low for Spring/Upthrust
TREND_LOOKBACK = 6        # (retained for reference; no longer used by trend logic below)
CONFIRM_FORWARD = 4        # weeks of look-forward confirmation
ABSORPTION_MAX_NET_MOVE_Z = 0.5  # net close-to-close move must be small (in spread units)

# ---- Swing-pivot trend detection (replaces bar-to-bar HH/HL counting) --
# A "minor swing" measure (counting raw week-over-week higher-highs) is
# noisy: it flags a choppy, range-bound stock as "trending" whenever a
# handful of individual weeks happen to tick upward. A professional
# Dow-theory/Wyckoff read of trend instead looks at the SEQUENCE OF SWING
# PIVOTS, not individual bars: an uptrend is a higher confirmed swing high
# AND a higher confirmed swing low than the prior pair of pivots. Anything
# else (flat, mixed, or contracting pivots) is a trading range, not a trend.
SWING_PIVOT_LOOKBACK = 3    # weeks on each side required to confirm a pivot
PIVOT_TOLERANCE = 0.02       # min % change between pivots to count as "clearly" higher/lower

# ---- Real-time breakdown/breakout override -----------------------------
# The confirmed-pivot method above has a blind spot: it only compares the
# last TWO CONFIRMED pivots, and confirmation takes SWING_PIVOT_LOOKBACK
# weeks. A fast, violent move (e.g. a crash) can push price well past any
# prior support before a new pivot has had time to confirm -- during which
# the classifier is still comparing against a stale, pre-move reference
# and can misread an active crash as an intact uptrend. This override adds
# a check using ONLY currently-known information (this bar's own high/low
# vs. the last CONFIRMED pivot, no lookahead): if price already breaks
# meaningfully past that confirmed reference, downgrade/upgrade the label
# immediately rather than waiting for confirmation to catch up.
#
# REQUIRES 2 CONSECUTIVE WEEKS of breach before firing (not just one) --
# a single-week spike is exactly the kind of noise this whole redesign
# was meant to filter out, not reintroduce. First version of this override
# fired on any single-bar breach and roughly tripled the whipsaw rate
# across validation tickers; requiring persistence brought that back down
# while still catching the 2020 COVID crash, which showed multiple
# consecutive breach weeks (see trend_validation.py).
OVERRIDE_BREACH_TOLERANCE = 0.05
OVERRIDE_MIN_CONSECUTIVE_WEEKS = 2


def _detect_swing_pivots(df: pd.DataFrame, n: int = SWING_PIVOT_LOOKBACK):
    """
    Fractal-style pivot detection: a bar is a swing high if its High is
    the maximum within a centered window of n bars on each side (swing
    low: minimum Low in the same window). Because this looks at n bars
    AFTER the pivot too, a pivot at position p is only CONFIRMED once
    we've reached position p+n -- it cannot be known in real time before
    then. That confirmation lag is handled in _classify_major_trend, not
    here; this function only marks where the pivots actually are.
    """
    window = 2 * n + 1
    is_swing_high = df["high"] == df["high"].rolling(window=window, center=True).max()
    is_swing_low = df["low"] == df["low"].rolling(window=window, center=True).min()
    return is_swing_high.fillna(False), is_swing_low.fillna(False)


def _classify_major_trend(df: pd.DataFrame, n: int = SWING_PIVOT_LOOKBACK,
                           tolerance: float = PIVOT_TOLERANCE) -> pd.Series:
    """
    Walks the bars in order, tracking the last two CONFIRMED swing highs
    and last two CONFIRMED swing lows as of each bar (a pivot at position
    p only becomes visible starting at position p+n). Classifies each bar
    into one of 5 states, using both swing legs together:

      - STRONG_UPTREND:   higher swing high AND higher swing low --
                           both legs confirming, clean structure.
      - WEAK_UPTREND:     bullish structure intact but only ONE leg has
                           confirmed and the other hasn't broken down --
                           e.g. price pulled back under the last high but
                           the swing low is still rising (correction
                           inside an uptrend), or a fresh higher high
                           hasn't been tested by a pullback yet.
      - STRONG_DOWNTREND: lower swing high AND lower swing low (mirror
                           of STRONG_UPTREND).
      - WEAK_DOWNTREND:   bearish structure intact but only one leg has
                           confirmed (mirror of WEAK_UPTREND).
      - SIDEWAYS_MARKET:  everything else -- flat pivots, not enough
                           confirmed history yet, OR genuinely conflicting
                           signals (e.g. a higher high paired with a lower
                           low). We deliberately do NOT force a directional
                           label onto a conflicting read; per the project's
                           own rule, if the structure itself doesn't
                           support a clean story, the tag shouldn't either.

    REAL-TIME OVERRIDE: after the base classification above, also checks
    whether THIS bar's own high/low has already broken meaningfully past
    the last CONFIRMED pivot (see OVERRIDE_BREACH_TOLERANCE). This catches
    fast, violent moves (e.g. a crash) that outrun the pivot-confirmation
    lag -- without it, a sharp multi-week decline can get stuck reading as
    an intact uptrend simply because no new pivot has had time to confirm
    yet. Validated against the 2020 COVID crash, which the base method
    alone missed entirely (see trend_validation.py).

    A plain Python loop is used deliberately over a vectorized trick --
    this is genuinely stateful sequential logic (tracking "the last two
    pivot values seen so far"), and staying explicit keeps it auditable.
    """
    is_swing_high, is_swing_low = _detect_swing_pivots(df, n)
    highs = df["high"].values
    lows = df["low"].values

    last_high_1 = last_high_2 = None
    last_low_1 = last_low_2 = None
    consecutive_breakdown_weeks = 0
    consecutive_breakout_weeks = 0
    labels = []

    for i in range(len(df)):
        confirm_idx = i - n
        if confirm_idx >= 0:
            if is_swing_high.iloc[confirm_idx]:
                last_high_2 = last_high_1
                last_high_1 = highs[confirm_idx]
            if is_swing_low.iloc[confirm_idx]:
                last_low_2 = last_low_1
                last_low_1 = lows[confirm_idx]

        if None not in (last_high_1, last_high_2, last_low_1, last_low_2):
            higher_high = last_high_1 > last_high_2 * (1 + tolerance)
            lower_high = last_high_1 < last_high_2 * (1 - tolerance)
            higher_low = last_low_1 > last_low_2 * (1 + tolerance)
            lower_low = last_low_1 < last_low_2 * (1 - tolerance)

            if higher_high and higher_low:
                base_label = "STRONG_UPTREND"
            elif lower_high and lower_low:
                base_label = "STRONG_DOWNTREND"
            elif (higher_low and not lower_high) or (higher_high and not lower_low):
                base_label = "WEAK_UPTREND"
            elif (lower_high and not higher_low) or (lower_low and not higher_high):
                base_label = "WEAK_DOWNTREND"
            else:
                base_label = "SIDEWAYS_MARKET"

            # Real-time override: has price ALREADY broken meaningfully past
            # the last confirmed pivot, faster than pivot confirmation can
            # catch up? Uses only this bar's own high/low -- no lookahead.
            # Requires OVERRIDE_MIN_CONSECUTIVE_WEEKS of sustained breach
            # before firing, so a single volatile week doesn't flip the label.
            breakdown_now = lows[i] < last_low_1 * (1 - OVERRIDE_BREACH_TOLERANCE)
            breakout_now = highs[i] > last_high_1 * (1 + OVERRIDE_BREACH_TOLERANCE)

            consecutive_breakdown_weeks = consecutive_breakdown_weeks + 1 if breakdown_now else 0
            consecutive_breakout_weeks = consecutive_breakout_weeks + 1 if breakout_now else 0

            breakdown_confirmed = consecutive_breakdown_weeks >= OVERRIDE_MIN_CONSECUTIVE_WEEKS
            breakout_confirmed = consecutive_breakout_weeks >= OVERRIDE_MIN_CONSECUTIVE_WEEKS

            if breakdown_confirmed and not breakout_confirmed:
                # A real, sustained breach is happening right now -- don't
                # let a stale confirmed-uptrend read stand. Escalate rather
                # than silently keep the old label.
                if base_label != "STRONG_DOWNTREND":
                    base_label = "WEAK_DOWNTREND"
            elif breakout_confirmed and not breakdown_confirmed:
                if base_label != "STRONG_UPTREND":
                    base_label = "WEAK_UPTREND"
            # if both breach in the same bar (rare, extreme volatility),
            # leave base_label as-is -- genuinely conflicting real-time
            # evidence, consistent with not forcing a label on mixed signals.

            labels.append(base_label)
        else:
            labels.append("INSUFFICIENT_HISTORY")

    return pd.Series(labels, index=df.index)


def _prior_trend_direction(df: pd.DataFrame, lookback: int) -> pd.Series:
    """
    Returns +1 if close was generally rising over the prior `lookback`
    weeks (before the current bar), -1 if generally falling, 0 if flat/mixed.
    Uses shift(1) so it never includes the current bar.
    """
    prior_close = df["close"].shift(1)
    lagged_close = df["close"].shift(1 + lookback)
    direction = np.sign(prior_close - lagged_close)
    return direction.fillna(0)


def assign_tags(weekly_df: pd.DataFrame) -> pd.DataFrame:
    df = weekly_df.copy()

    prior_trend = _prior_trend_direction(df, CONTEXT_LOOKBACK)
    is_up_week = df["close"] > df["close"].shift(1)
    is_down_week = df["close"] < df["close"].shift(1)

    # ---------------- SELLING_CLIMAX (Wyckoff Event) ----------------
    df["SELLING_CLIMAX"] = (
        (df["vol_pctile"] > HIGH_VOL_PCTILE) &
        (df["spread_pctile"] > HIGH_SPREAD_PCTILE) &
        (df["clv"] < WEAK_CLV) &
        (prior_trend < 0)
    )

    # ---------------- BUYING_CLIMAX (Supply) ----------------
    df["BUYING_CLIMAX"] = (
        (df["vol_pctile"] > HIGH_VOL_PCTILE) &
        (df["spread_pctile"] > HIGH_SPREAD_PCTILE) &
        (df["clv"] < STRONG_CLV) &   # wide up-ish bar but NOT closing strong = supply showing
        (prior_trend > 0) &
        is_up_week
    )

    # ---------------- NO_SUPPLY (Demand) ----------------
    df["NO_SUPPLY"] = (
        (df["spread_pctile"] < LOW_SPREAD_PCTILE) &
        (df["vol_pctile"] < LOW_VOL_PCTILE) &
        is_down_week &
        (prior_trend > 0)
    )

    # ---------------- NO_DEMAND (Wyckoff Event) ----------------
    df["NO_DEMAND"] = (
        (df["spread_pctile"] < LOW_SPREAD_PCTILE) &
        (df["vol_pctile"] < LOW_VOL_PCTILE) &
        is_up_week &
        (prior_trend < 0)
    )

    # ---------------- STOPPING_VOLUME (Demand) ----------------
    df["STOPPING_VOLUME"] = (
        (df["vol_pctile"] > HIGH_VOL_PCTILE) &
        (df["clv"] > STRONG_CLV) &
        (prior_trend < 0)
    )

    # ---------------- SPRING (Wyckoff Phase C) ----------------
    range_low = df["low"].shift(1).rolling(window=RANGE_LOOKBACK).min()
    broke_below = df["low"] < range_low
    closed_back_above = df["close"] > range_low
    spring_raw = broke_below & closed_back_above & (df["clv"] > STRONG_CLV)

    # Look-forward confirmation: price must NOT close below this bar's low
    # in the next CONFIRM_FORWARD weeks. NaN (=pending) if not enough future data yet.
    future_min_close = df["close"].shift(-1).rolling(window=CONFIRM_FORWARD).min().shift(-(CONFIRM_FORWARD - 1))
    enough_future = df["close"].shift(-CONFIRM_FORWARD).notna()
    spring_confirmed = spring_raw & (future_min_close > df["low"])
    # NOTE: built via pandas object-dtype assignment, NOT np.where -- np.where
    # silently coerces the WHOLE array to a single dtype when mixing strings
    # ("CONFIRMED"/"PENDING") with a boolean (False), turning every False into
    # the STRING "False". That bug shipped invisibly until Step 6's tiering
    # code did a naive `!= False` check and got "everything fired." Explicit
    # object-dtype assignment avoids the coercion entirely.
    spring_col = pd.Series(False, index=df.index, dtype=object)
    spring_col[spring_confirmed] = "CONFIRMED"
    spring_col[~enough_future & spring_raw & ~spring_confirmed] = "PENDING"
    df["SPRING"] = spring_col

    # ---------------- UPTHRUST (Wyckoff Event) ----------------
    range_high = df["high"].shift(1).rolling(window=RANGE_LOOKBACK).max()
    broke_above = df["high"] > range_high
    closed_back_below = df["close"] < range_high
    upthrust_raw = broke_above & closed_back_below & (df["clv"] < WEAK_CLV)

    future_max_close = df["close"].shift(-1).rolling(window=CONFIRM_FORWARD).max().shift(-(CONFIRM_FORWARD - 1))
    upthrust_confirmed = upthrust_raw & (future_max_close < df["high"])
    upthrust_col = pd.Series(False, index=df.index, dtype=object)
    upthrust_col[upthrust_confirmed] = "CONFIRMED"
    upthrust_col[~enough_future & upthrust_raw & ~upthrust_confirmed] = "PENDING"
    df["UPTHRUST"] = upthrust_col

    # ---------------- STRONG_UPTREND / STRONG_DOWNTREND / SIDEWAYS_MARKET (Trend Basics) ----------------
    # Now classified from the SEQUENCE OF SWING PIVOTS (major trend), not
    # raw bar-to-bar higher-highs (minor swing noise). See
    # _classify_major_trend for the full reasoning.
    major_trend = _classify_major_trend(df)
    df["MAJOR_TREND"] = major_trend  # kept as a readable label for diagnostics/reporting
    df["STRONG_UPTREND"] = major_trend == "STRONG_UPTREND"
    df["WEAK_UPTREND"] = major_trend == "WEAK_UPTREND"
    df["STRONG_DOWNTREND"] = major_trend == "STRONG_DOWNTREND"
    df["WEAK_DOWNTREND"] = major_trend == "WEAK_DOWNTREND"
    df["SIDEWAYS_MARKET"] = major_trend == "SIDEWAYS_MARKET"

    # ---------------- ABSORPTION (Effort vs Result) ----------------
    # High effort (wide spread or high volume) but small net result (close barely moved)
    net_move = (df["close"] - df["close"].shift(1)).abs()
    net_move_z = net_move / (df["spread"].rolling(window=20).mean() + 1e-10)
    df["net_move_z"] = net_move_z  # exposed as a column for Step 6's signal-strength tiering
    df["ABSORPTION"] = (
        ((df["vol_z"] > HIGH_VOL_Z) | (df["spread_z"] > HIGH_SPREAD_Z)) &
        (net_move_z < ABSORPTION_MAX_NET_MOVE_Z)
    )

    return df


def tag_all_tickers(weekly_data: dict) -> dict:
    tagged = {}
    for ticker, wdf in weekly_data.items():
        tagged[ticker] = assign_tags(wdf)
    return tagged


TAG_COLUMNS = [
    "SELLING_CLIMAX", "BUYING_CLIMAX", "NO_SUPPLY", "NO_DEMAND",
    "STOPPING_VOLUME", "SPRING", "UPTHRUST",
    "STRONG_UPTREND", "WEAK_UPTREND", "STRONG_DOWNTREND", "WEAK_DOWNTREND",
    "SIDEWAYS_MARKET", "ABSORPTION",
]


if __name__ == "__main__":
    stock_data = ingest_all_stocks()
    passed_data, _ = filter_universe(stock_data)
    weekly_data = build_weekly_dataset(passed_data)
    tagged_data = tag_all_tickers(weekly_data)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    print("=" * 100)
    print("STEP 4: TAG FREQUENCY SUMMARY (count of weeks each tag fired, per ticker)")
    print("=" * 100)

    freq_rows = []
    for ticker, tdf in tagged_data.items():
        row = {"ticker": ticker}
        for tag in TAG_COLUMNS:
            if tag in ("SPRING", "UPTHRUST"):
                row[tag] = (tdf[tag] == "CONFIRMED").sum()
                row[f"{tag}_pending"] = (tdf[tag] == "PENDING").sum()
            else:
                row[tag] = int(tdf[tag].sum())
        freq_rows.append(row)

    freq_df = pd.DataFrame(freq_rows).sort_values("ticker").reset_index(drop=True)
    print(freq_df.to_string(index=False))

    print("\n" + "=" * 100)
    print("SAMPLE: most recent 10 weekly bars for HDFCBANK with all tag columns")
    print("=" * 100)
    if "HDFCBANK" in tagged_data:
        sample_cols = ["week_start", "close", "high", "low", "MAJOR_TREND"] + [
            c for c in TAG_COLUMNS if c not in (
                "STRONG_UPTREND", "WEAK_UPTREND", "STRONG_DOWNTREND", "WEAK_DOWNTREND", "SIDEWAYS_MARKET"
            )
        ]
        print(tagged_data["HDFCBANK"][sample_cols].tail(10).to_string(index=False))

    print("\n" + "=" * 100)
    print("SPOT CHECK: first ticker with at least one CONFIRMED SPRING, if any")
    print("=" * 100)
    found = False
    for ticker, tdf in tagged_data.items():
        springs = tdf[tdf["SPRING"] == "CONFIRMED"]
        if len(springs) > 0:
            print(f"\nTicker: {ticker}")
            print(springs[["week_start", "low", "close", "clv", "vol_pctile", "spread_pctile"]].to_string(index=False))
            found = True
            break
    if not found:
        print("No CONFIRMED Springs found in this universe/date range -- "
              "not necessarily a bug, Springs are meant to be rare structural events. "
              "Check the *_pending counts above; some may still be awaiting look-forward confirmation.")
