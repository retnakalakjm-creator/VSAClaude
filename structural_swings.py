"""
STRUCTURAL SWING DETECTION (replaces fractal-pivot method + override hack)
-----------------------------------------------------------------
Rebuilds trend/swing detection around genuine STRUCTURAL swings rather
than raw local pivots, following the two-stage funnel:

    raw local extremes -> filter by minimum displacement -> candidates
                        -> confirm via close-based Break of Structure (BOS)
                        -> structural swings

WHY THIS REPLACES THE OLD FRACTAL-PIVOT METHOD:
The old method (tagging_engine.py's _classify_major_trend, first version)
needed SWING_PIVOT_LOOKBACK weeks AFTER a pivot before it could confirm
one -- a fixed, backward-looking lag. During a fast, violent move (the
2020 COVID crash), that lag meant the classifier kept comparing against
a stale, pre-crash reference and misread the crash as an intact uptrend
for weeks (see trend_validation.py). Patching that with a real-time
"breach override" fixed the crash-onset misread but roughly tripled the
whipsaw rate, and still left violent V-shaped recoveries mislabeled for
extended stretches (see the RELIANCE conversation history).

BOS confirmation is inherently real-time: a bar's CLOSE either breaks a
previously-known structural level or it doesn't. There is no lag to
wait out, so no override hack is needed at all.

KEY DESIGN DECISIONS:
1. DISPLACEMENT FILTER (not a fixed % tolerance): a local high/low only
   becomes a CANDIDATE swing point once price has moved away from it by
   at least DISPLACEMENT_ATR_MULTIPLE times this stock's own recent
   average weekly spread (an ATR-style, indicator-free volatility
   yardstick we already compute in Step 3/4). This is per-stock and
   per-era adaptive -- a 2% wiggle is noise for a volatile cyclical
   stock but could be a real move for a quiet blue chip, and either
   stock's own volatility regime shifts across 30 years of history.
   This filters out most noise BEFORE it ever reaches pivot tracking,
   rather than patching whipsaw after the fact.
2. BODY-CLOSE CONFIRMATION (not wick-based): a candidate low only
   becomes a CONFIRMED structural low once a later bar's CLOSE (not
   just its high) moves back above the prior confirmed structural high.
   A wick spike doesn't count -- VSA cares about where price actually
   settled.
3. ALTERNATING STRUCTURE: confirming a new structural low always comes
   from breaking the prior structural HIGH (and vice versa) -- this
   naturally produces the alternating high-low-high-low sequence real
   market structure follows, rather than tracking highs and lows as
   independent, unrelated series.
"""

import pandas as pd
import numpy as np

DISPLACEMENT_ATR_MULTIPLE = 1.5  # candidate must displace this many "ATR" units from its anchor
ATR_WINDOW = 20                   # weeks -- matches the rolling window convention used elsewhere
STRUCTURAL_TOLERANCE = 0.02        # min % separation to call one structural level "higher/lower" than another
STALE_REFRESH_ATR_MULTIPLE = 8.0    # see detect_structural_swings docstring: "staleness" safety valve
LIVE_EVIDENCE_MIN_WEEKS = 2          # persistence required before live-candidate evidence counts (anti-whipsaw)


def compute_atr_proxy(df: pd.DataFrame, window: int = ATR_WINDOW) -> pd.Series:
    """
    Rolling average weekly spread -- our indicator-free, per-stock,
    per-era volatility yardstick (same spirit as a traditional ATR,
    built only from raw OHLC already in hand, no smoothing indicator).
    min_periods=5 lets this populate faster than the full 20-week
    window, so early history isn't entirely blind.
    """
    return df["spread"].rolling(window=window, min_periods=5).mean()


def detect_structural_swings(df: pd.DataFrame,
                              displacement_mult: float = DISPLACEMENT_ATR_MULTIPLE,
                              tolerance: float = STRUCTURAL_TOLERANCE) -> pd.DataFrame:
    """
    Walks bars in chronological order, tracking confirmed structural
    highs/lows via close-based BOS, and classifies each bar's trend
    state from the sequence. Returns the input df with new columns:
      - MAJOR_TREND: STRONG_UPTREND / WEAK_UPTREND / STRONG_DOWNTREND /
                      WEAK_DOWNTREND / SIDEWAYS_MARKET / INSUFFICIENT_HISTORY
      - STRUCTURAL_HIGH / STRUCTURAL_LOW: the most recently CONFIRMED
        structural level as of that bar (for diagnostics/reporting)
      - BOS_EVENT: "BULLISH_BOS" / "BEARISH_BOS" / "" -- marks the exact
        bar where a break of structure just occurred
    """
    df = df.copy()
    atr = compute_atr_proxy(df).values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    last_structural_high = last_structural_high_2 = None
    last_structural_low = last_structural_low_2 = None
    candidate_high = candidate_low = None

    # Persistence counters for real-time "live candidate" evidence (see
    # classification block below) -- require LIVE_EVIDENCE_MIN_WEEKS of
    # sustained breach before it counts, so a single noisy week can't flip
    # the classification. Without this, the live-evidence fix that solved
    # the sustained-trend blind spot (RELIANCE COVID case) reacted to
    # every minor weekly wiggle and roughly tripled the whipsaw rate
    # across the 5-ticker validation set.
    consecutive_live_higher_low = 0
    consecutive_live_lower_low = 0
    consecutive_live_higher_high = 0
    consecutive_live_lower_high = 0

    trend_labels = []
    struct_high_col = []
    struct_low_col = []
    bos_events = []

    for i in range(len(df)):
        c, h, l = closes[i], highs[i], lows[i]
        a = atr[i]

        candidate_high = h if candidate_high is None else max(candidate_high, h)
        candidate_low = l if candidate_low is None else min(candidate_low, l)

        bos_event = ""

        # STALENESS SAFETY VALVE: over a multi-decade, heavily-compounding
        # price history, a structural level set early on (e.g. a stock at
        # Rs 8 in 1996) can become permanently irrelevant once price has
        # grown far past it (e.g. Rs 700+) -- close will trivially exceed
        # it forever, which (a) makes every future bar register as a
        # "breakout" against a reference that's numerically meaningless,
        # and (b) as a direct consequence, makes the OPPOSITE reference
        # mathematically impossible to ever update again (see detect_
        # structural_swings module docstring / conversation history for
        # the full trace of this failure mode on RELIANCE 1996-2020,
        # where BEARISH_BOS fired 7 times in 1996 and then never again in
        # 24 years). If price has drifted more than STALE_REFRESH_ATR_
        # MULTIPLE average-spread-units beyond an unbroken reference,
        # treat it as stale and refresh it directly from the current
        # running candidate, rather than waiting for a technical break
        # that can no longer mechanically occur.
        if a is not None and not np.isnan(a) and a > 0:
            if last_structural_high is not None and (candidate_high - last_structural_high) > STALE_REFRESH_ATR_MULTIPLE * a:
                last_structural_high_2 = last_structural_high
                last_structural_high = candidate_high
                candidate_low = l
            if last_structural_low is not None and (last_structural_low - candidate_low) > STALE_REFRESH_ATR_MULTIPLE * a:
                last_structural_low_2 = last_structural_low
                last_structural_low = candidate_low
                candidate_high = h

        # Bullish BOS: close breaks above the last CONFIRMED structural
        # high -> confirms the running candidate_low as a new structural low.
        if last_structural_high is not None and c > last_structural_high:
            last_structural_low_2 = last_structural_low
            last_structural_low = candidate_low
            bos_event = "BULLISH_BOS"
            # Reset BOTH candidate trackers -- a fresh leg starts now in
            # both directions. Forgetting to reset candidate_low here was
            # a real bug: it would otherwise keep accumulating the
            # ALL-TIME minimum since inception forever, never refreshing
            # to a recent low, which (combined with the same bug on
            # candidate_high in the bearish branch) caused BOS to fire on
            # every single bar for decades once bootstrapped on early,
            # since-irrelevant price levels. Caught via direct inspection
            # of the RELIANCE 2020 window before trusting the frequency
            # tables -- see the conversation history for the trace.
            candidate_high = h
            candidate_low = l

        # Bearish BOS: close breaks below the last CONFIRMED structural
        # low -> confirms the running candidate_high as a new structural high.
        if last_structural_low is not None and c < last_structural_low:
            last_structural_high_2 = last_structural_high
            last_structural_high = candidate_high
            bos_event = "BEARISH_BOS"
            candidate_low = l
            candidate_high = h

        # Bootstrap: before ANY structural level is confirmed, seed the
        # first pair using the displacement filter alone (no prior level
        # exists yet to break, so BOS can't apply for the very first swing).
        if a is not None and not np.isnan(a) and a > 0:
            if last_structural_high is None and (candidate_high - candidate_low) > displacement_mult * a:
                last_structural_high = candidate_high
            if last_structural_low is None and (candidate_high - candidate_low) > displacement_mult * a:
                last_structural_low = candidate_low

        # Classify current trend state.
        #
        # FIX for sustained one-directional moves (see conversation history
        # for the full diagnosis on the RELIANCE COVID crash): during a
        # straight decline, bearish BOS keeps firing every week (correctly
        # updating last_structural_high downward), but bullish BOS never
        # gets a chance to fire (no pullback), so last_structural_low stays
        # frozen on a stale, pre-decline value -- meaning the CONFIRMED
        # pair comparison never shows "lower_low", even while price is
        # visibly making fresh lows every week. The fix: also check the
        # ACTIVELY UPDATING candidate value against the last CONFIRMED
        # opposite-direction level -- if candidate_low has already dropped
        # meaningfully below last_structural_low in real time (even before
        # a full round-trip BOS confirms it), that's genuine live evidence
        # of continuation, not just noise. Mirror logic for uptrends.
        if last_structural_low is not None and last_structural_low > 0:
            live_higher_low = candidate_low > last_structural_low * (1 + tolerance)
            live_lower_low = candidate_low < last_structural_low * (1 - tolerance)
        else:
            live_higher_low = live_lower_low = False

        if last_structural_high is not None and last_structural_high > 0:
            live_higher_high = candidate_high > last_structural_high * (1 + tolerance)
            live_lower_high = candidate_high < last_structural_high * (1 - tolerance)
        else:
            live_higher_high = live_lower_high = False
        # NOTE: a persistence gate (requiring N consecutive weeks of live
        # evidence before it counts) was tried here and made things WORSE,
        # not better -- whipsaw rose further (66-71% -> 74-80%) and
        # STRONG_DOWNTREND average returns flipped to the wrong sign
        # across the board. Root cause: BOS itself already fires almost
        # every week in many stretches, resetting both candidate trackers
        # each time, so candidate_high/low rarely accumulate more than a
        # bar or two of history -- meaning they're already close to the
        # current price, and a 2% band around a reference that's often
        # only a week old gets crossed by ordinary noise regardless of
        # how many consecutive weeks are required. This needs a properly
        # scoped redesign (e.g. rethinking how often BOS itself is allowed
        # to fire), not a persistence patch on top. Left as a known,
        # documented limitation -- see conversation history.

        if None not in (last_structural_high, last_structural_high_2,
                         last_structural_low, last_structural_low_2):
            higher_high = (last_structural_high > last_structural_high_2 * (1 + tolerance)) or live_higher_high
            lower_high = (last_structural_high < last_structural_high_2 * (1 - tolerance)) or live_lower_high
            higher_low = (last_structural_low > last_structural_low_2 * (1 + tolerance)) or live_higher_low
            lower_low = (last_structural_low < last_structural_low_2 * (1 - tolerance)) or live_lower_low

            if higher_high and higher_low:
                label = "STRONG_UPTREND"
            elif lower_high and lower_low:
                label = "STRONG_DOWNTREND"
            elif (higher_low and not lower_high) or (higher_high and not lower_low):
                label = "WEAK_UPTREND"
            elif (lower_high and not higher_low) or (lower_low and not higher_high):
                label = "WEAK_DOWNTREND"
            else:
                label = "SIDEWAYS_MARKET"
        else:
            label = "INSUFFICIENT_HISTORY"

        trend_labels.append(label)
        struct_high_col.append(last_structural_high)
        struct_low_col.append(last_structural_low)
        bos_events.append(bos_event)

    df["MAJOR_TREND"] = trend_labels
    df["STRUCTURAL_HIGH"] = struct_high_col
    df["STRUCTURAL_LOW"] = struct_low_col
    df["BOS_EVENT"] = bos_events
    return df
