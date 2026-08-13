"""
STEP 5: DAILY TAGGING ENGINE (with weekly background gating)
-----------------------------------------------------------------
Goal: Tag daily bars with 5 "timing" signals -- NO_SUPPLY, NO_DEMAND,
TEST, SHAKEOUT, UPTHRUST -- using daily-native rolling percentile
context (NOT weekly), and require each tag to agree with the prevailing
WEEKLY background before it counts as confirmed.

CORE PRINCIPLE (per user direction):
  Weekly chart = the story (background). Daily chart = the trigger
  (timing). A daily pattern that mechanically "looks like" No Supply
  means very little on its own -- it only becomes meaningful VSA
  evidence when the broader weekly background already favors that
  read. So background is baked into each tag's definition here, not
  applied as an afterthought.

WEEKLY BIAS (interim proxy -- Step 7 will replace this with a fuller
background synthesis):
  For each week, tally how many of Step 4's weekly tags lean bullish
  vs bearish. Sum that lean over a trailing 4-week window -> FAVORABLE
  / UNFAVORABLE / NEUTRAL. This is intentionally simple; some Step 4
  tags (SELLING_CLIMAX, ABSORPTION) are genuinely ambiguous in
  direction and are deliberately left OUT of this scoring rather than
  guessed at.

NO LOOK-AHEAD BIAS: a daily bar can only "see" the most recently
FULLY COMPLETED prior week's bias -- never the week still in progress
(which includes bars not yet known, including itself). Implemented via
merge_asof with each week's bias only becoming visible starting the
day AFTER that week's Friday close.

REAL-MARKET PRAGMATISM: per user's reminder, textbook VSA setups
rarely appear in full in live data. Each tag below uses 3-4 conditions
max -- not every attribute a textbook would list -- to avoid building
patterns so narrow they never fire. Thresholds here are a first pass
and are expected to need tuning once you've eyeballed real examples.

Depends on Steps 1-4 and does not modify them.
"""

import pandas as pd
import numpy as np
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe
from weekly_metrics import build_weekly_dataset
from tagging_engine import tag_all_tickers, TAG_COLUMNS

# ---- Daily-native rolling percentile window ----------------------------
DAILY_ROLLING_WINDOW = 20  # trading days (~1 month)

# ---- Daily tag thresholds (percentile-based, same philosophy as Step 4) --
LOW_SPREAD_PCTILE = 0.35
LOW_VOL_PCTILE = 0.35
HIGH_SPREAD_PCTILE = 0.80
HIGH_VOL_PCTILE = 0.80
STRONG_CLV = 0.65
WEAK_CLV = 0.35

# ---- Short-term range lookback for Test/Shakeout/Upthrust breakouts ----
DAILY_RANGE_LOOKBACK = 10  # trading days (~2 weeks)

# ---- Weekly bias scoring ------------------------------------------------
BIAS_LOOKBACK_WEEKS = 4
# Tags with an unambiguous directional lean. SELLING_CLIMAX and ABSORPTION
# are deliberately excluded -- their direction depends on subsequent bars,
# not the bar itself, so guessing a sign here would be dishonest.
BULLISH_WEEKLY_TAGS = ["NO_SUPPLY", "STOPPING_VOLUME", "STRONG_UPTREND"]
BEARISH_WEEKLY_TAGS = ["NO_DEMAND", "BUYING_CLIMAX", "STRONG_DOWNTREND"]


def compute_weekly_bias(weekly_tagged_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each weekly bar, count bullish-leaning vs bearish-leaning tags
    fired that week, then sum that lean over the trailing
    BIAS_LOOKBACK_WEEKS weeks (inclusive of the current week -- safe,
    since by the time this week's own bar is complete, its tags are
    fully known).
    Returns weekly_tagged_df with two new columns: bias_score, bias_label.
    """
    df = weekly_tagged_df.copy()

    bullish_count = df[BULLISH_WEEKLY_TAGS].astype(bool).sum(axis=1)
    # SPRING/UPTHRUST are stored as "CONFIRMED"/"PENDING"/False, not plain bool
    bullish_count += (df["SPRING"] == "CONFIRMED").astype(int)

    bearish_count = df[BEARISH_WEEKLY_TAGS].astype(bool).sum(axis=1)
    bearish_count += (df["UPTHRUST"] == "CONFIRMED").astype(int)

    weekly_lean = bullish_count - bearish_count
    df["bias_score"] = weekly_lean.rolling(window=BIAS_LOOKBACK_WEEKS).sum()

    df["bias_label"] = np.select(
        [df["bias_score"] > 0, df["bias_score"] < 0],
        ["FAVORABLE", "UNFAVORABLE"],
        default="NEUTRAL",
    )
    # Bars before enough history exists for a real bias reading
    df.loc[df["bias_score"].isna(), "bias_label"] = "INSUFFICIENT_HISTORY"

    return df


def attach_weekly_bias_to_daily(daily_df: pd.DataFrame, weekly_bias_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merges each daily bar with the bias of the most recently COMPLETED
    prior week -- never the week still in progress. A week's bias
    becomes visible starting the day AFTER that week's Friday close.
    """
    daily = daily_df.sort_values("date").copy()
    weekly = weekly_bias_df[["week_end", "bias_score", "bias_label"]].copy()
    weekly = weekly.sort_values("week_end")
    weekly["usable_from"] = weekly["week_end"] + pd.Timedelta(days=1)

    merged = pd.merge_asof(
        daily, weekly,
        left_on="date", right_on="usable_from",
        direction="backward",
    )
    merged["bias_label"] = merged["bias_label"].fillna("INSUFFICIENT_HISTORY")
    return merged.drop(columns=["usable_from", "week_end"], errors="ignore")


def compute_daily_metrics(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Daily-native spread, CLV, and rolling percentile ranks (20-day)."""
    df = daily_df.copy()
    df["spread"] = df["high"] - df["low"]
    df["clv"] = (df["close"] - df["low"]) / (df["spread"] + 1e-10)

    def pct_rank_of_last(w):
        return (w <= w[-1]).mean()

    df["spread_pctile"] = df["spread"].rolling(window=DAILY_ROLLING_WINDOW).apply(pct_rank_of_last, raw=True)
    df["vol_pctile"] = df["volume"].rolling(window=DAILY_ROLLING_WINDOW).apply(pct_rank_of_last, raw=True)
    return df


def assign_daily_tags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    is_up_day = df["close"] > df["close"].shift(1)
    is_down_day = df["close"] < df["close"].shift(1)

    favorable = df["bias_label"] == "FAVORABLE"
    unfavorable = df["bias_label"] == "UNFAVORABLE"

    # ---------------- NO_SUPPLY ----------------
    # Down bar + narrow spread + low volume + favorable (strong) background
    df["NO_SUPPLY"] = (
        is_down_day &
        (df["spread_pctile"] < LOW_SPREAD_PCTILE) &
        (df["vol_pctile"] < LOW_VOL_PCTILE) &
        favorable
    )

    # ---------------- NO_DEMAND ----------------
    # Up bar + narrow spread + low volume + unfavorable (weak) background
    df["NO_DEMAND"] = (
        is_up_day &
        (df["spread_pctile"] < LOW_SPREAD_PCTILE) &
        (df["vol_pctile"] < LOW_VOL_PCTILE) &
        unfavorable
    )

    # ---------------- TEST ----------------
    # Quiet probe below a recent short-term low, closes back above it,
    # on volume that is NOT elevated (a genuine test happens on light
    # supply), in a background that isn't actively hostile.
    recent_low = df["low"].shift(1).rolling(window=DAILY_RANGE_LOOKBACK).min()
    df["TEST"] = (
        (df["low"] < recent_low) &
        (df["close"] > recent_low) &
        (df["vol_pctile"] < 0.50) &
        (df["clv"] > STRONG_CLV) &
        (~unfavorable)
    )

    # ---------------- SHAKEOUT ----------------
    # Violent version of TEST: wide spread + high volume, but still
    # recovers to a strong close -- a sharp flush that gets absorbed.
    df["SHAKEOUT"] = (
        (df["low"] < recent_low) &
        (df["close"] > recent_low) &
        (df["spread_pctile"] > HIGH_SPREAD_PCTILE) &
        (df["vol_pctile"] > HIGH_VOL_PCTILE) &
        (df["clv"] > STRONG_CLV) &
        (~unfavorable)
    )

    # ---------------- UPTHRUST ----------------
    # Breaks above a recent short-term high but closes back below it,
    # wide spread, high volume, weak close -- more credible as real
    # supply when the background isn't already strongly favorable.
    recent_high = df["high"].shift(1).rolling(window=DAILY_RANGE_LOOKBACK).max()
    df["UPTHRUST"] = (
        (df["high"] > recent_high) &
        (df["close"] < recent_high) &
        (df["spread_pctile"] > HIGH_SPREAD_PCTILE) &
        (df["vol_pctile"] > HIGH_VOL_PCTILE) &
        (df["clv"] < WEAK_CLV) &
        (~favorable)
    )

    return df


DAILY_TAG_COLUMNS = ["NO_SUPPLY", "NO_DEMAND", "TEST", "SHAKEOUT", "UPTHRUST"]


def build_daily_tagged_dataset(stock_data: dict, weekly_tagged_data: dict) -> dict:
    """
    Full Step 5 pipeline per ticker: compute weekly bias, attach it to
    daily bars (no look-ahead), compute daily percentile metrics, then
    assign daily tags.
    """
    result = {}
    for ticker, daily_df in stock_data.items():
        if ticker not in weekly_tagged_data:
            continue
        weekly_bias_df = compute_weekly_bias(weekly_tagged_data[ticker])
        daily_with_bias = attach_weekly_bias_to_daily(daily_df, weekly_bias_df)
        daily_with_metrics = compute_daily_metrics(daily_with_bias)
        daily_tagged = assign_daily_tags(daily_with_metrics)
        result[ticker] = daily_tagged
    return result


if __name__ == "__main__":
    stock_data = ingest_all_stocks()
    passed_data, _ = filter_universe(stock_data)
    weekly_data = build_weekly_dataset(passed_data)
    weekly_tagged = tag_all_tickers(weekly_data)
    daily_tagged = build_daily_tagged_dataset(passed_data, weekly_tagged)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    print("=" * 100)
    print("STEP 5: DAILY TAG FREQUENCY SUMMARY (count of days each tag fired, per ticker)")
    print("=" * 100)

    freq_rows = []
    for ticker, ddf in daily_tagged.items():
        row = {"ticker": ticker, "total_days": len(ddf)}
        for tag in DAILY_TAG_COLUMNS:
            row[tag] = int(ddf[tag].sum())
        freq_rows.append(row)
    freq_df = pd.DataFrame(freq_rows).sort_values("ticker").reset_index(drop=True)
    print(freq_df.to_string(index=False))

    # Diagnostic: how much does the background gate actually filter out?
    print("\n" + "=" * 100)
    print("DIAGNOSTIC: background-gating impact on NO_SUPPLY / NO_DEMAND")
    print("(shows how many bars matched the MECHANICAL pattern alone vs "
          "after requiring the matching background)")
    print("=" * 100)
    if "HDFCBANK" in daily_tagged:
        h = daily_tagged["HDFCBANK"]
        is_up_day = h["close"] > h["close"].shift(1)
        is_down_day = h["close"] < h["close"].shift(1)
        raw_no_supply = (is_down_day & (h["spread_pctile"] < LOW_SPREAD_PCTILE) & (h["vol_pctile"] < LOW_VOL_PCTILE)).sum()
        raw_no_demand = (is_up_day & (h["spread_pctile"] < LOW_SPREAD_PCTILE) & (h["vol_pctile"] < LOW_VOL_PCTILE)).sum()
        print(f"HDFCBANK -- NO_SUPPLY: {raw_no_supply} mechanical matches -> {h['NO_SUPPLY'].sum()} after background gate")
        print(f"HDFCBANK -- NO_DEMAND: {raw_no_demand} mechanical matches -> {h['NO_DEMAND'].sum()} after background gate")

    print("\n" + "=" * 100)
    print("SAMPLE: most recent 15 daily bars for HDFCBANK with bias + tags")
    print("=" * 100)
    if "HDFCBANK" in daily_tagged:
        cols = ["date", "close", "spread_pctile", "vol_pctile", "clv", "bias_label"] + DAILY_TAG_COLUMNS
        print(daily_tagged["HDFCBANK"][cols].tail(15).to_string(index=False))
