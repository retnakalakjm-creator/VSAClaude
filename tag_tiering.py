"""
STEP 6: MAJOR / MINOR / NEUTRAL SIGNAL TIERING
-----------------------------------------------------------------
Goal: Replace flat True/False tags with a 3-tier read of conviction:

  MAJOR_SIGNAL       -- the tag fired, AND the underlying evidence sits
                         well past its qualifying threshold (a genuinely
                         convincing instance).
  MINOR_OBSERVATION  -- the tag fired, but only marginally cleared the
                         threshold (worth noting, not worth trading on
                         its own).
  NEUTRAL            -- the tag did not fire at all.

Per the project's own principle: not every bar should be forced into a
named pattern. A tag that barely scrapes past its cutoff (e.g.
vol_pctile = 0.86 when the bar is 0.85) is real evidence, but it is NOT
the same quality of evidence as vol_pctile = 0.99 -- treating them
identically as a flat boolean throws away exactly the information a
human analyst would use to judge conviction.

HOW STRENGTH IS SCORED:
For each tag, we identify its CONTINUOUS drivers (percentile ranks and
CLV -- the graded evidence) as opposed to its CATEGORICAL gates (up/down
week, prior trend direction, background label -- binary context that
either permits or blocks the tag, but doesn't come in degrees). For each
continuous driver we compute an "extremity" score: 0.0 at the threshold,
1.0 at the theoretical extreme (e.g. percentile of 1.0, or CLV of 0/1).
A tag's overall strength is the average extremity across its drivers.
TIER_MAJOR_THRESHOLD decides where "minor" ends and "major" begins.

NOTE ON SCOPE: trend classification tags (STRONG_UPTREND, SIDEWAYS_MARKET,
etc.) are deliberately NOT tiered here -- they are state classifications,
not discrete events, so "how major is this uptrend" isn't the same kind
of question as "how major is this Selling Climax."

Depends on Steps 1-5 and does not modify their tagging logic (only adds
one previously-internal column, net_move_z, in tagging_engine.py, needed
here for ABSORPTION's strength score).
"""

import pandas as pd
from ingestion import ingest_all_stocks
from liquidity_filters import filter_universe
from weekly_metrics import build_weekly_dataset
from tagging_engine import (
    tag_all_tickers, HIGH_VOL_PCTILE, HIGH_SPREAD_PCTILE, LOW_VOL_PCTILE,
    LOW_SPREAD_PCTILE, WEAK_CLV, STRONG_CLV, ABSORPTION_MAX_NET_MOVE_Z,
)
from daily_tagging import build_daily_tagged_dataset, DAILY_TAG_COLUMNS

TIER_MAJOR_THRESHOLD = 0.40  # composite strength >= this -> MAJOR_SIGNAL


def _extremity_high(series: pd.Series, threshold: float) -> pd.Series:
    """0.0 right at the threshold, 1.0 at the theoretical max (1.0)."""
    return ((series - threshold) / (1 - threshold)).clip(lower=0, upper=1)


def _extremity_low(series: pd.Series, threshold: float) -> pd.Series:
    """0.0 right at the threshold, 1.0 at the theoretical min (0.0)."""
    return ((threshold - series) / threshold).clip(lower=0, upper=1)


def _extremity_low_bounded(series: pd.Series, threshold: float) -> pd.Series:
    """For 'smaller is more extreme, bounded below the threshold' drivers
    like net_move_z in ABSORPTION (0 net move = max strength)."""
    return ((threshold - series) / threshold).clip(lower=0, upper=1)


# Maps each event tag to its continuous strength drivers:
# (column_name, extremity_function, threshold)
WEEKLY_TAG_DRIVERS = {
    "SELLING_CLIMAX": [
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("spread_pctile", _extremity_high, HIGH_SPREAD_PCTILE),
        ("clv", _extremity_low, WEAK_CLV),
    ],
    "BUYING_CLIMAX": [
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("spread_pctile", _extremity_high, HIGH_SPREAD_PCTILE),
        ("clv", _extremity_low, STRONG_CLV),
    ],
    "NO_SUPPLY": [
        ("spread_pctile", _extremity_low, LOW_SPREAD_PCTILE),
        ("vol_pctile", _extremity_low, LOW_VOL_PCTILE),
    ],
    "NO_DEMAND": [
        ("spread_pctile", _extremity_low, LOW_SPREAD_PCTILE),
        ("vol_pctile", _extremity_low, LOW_VOL_PCTILE),
    ],
    "STOPPING_VOLUME": [
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("clv", _extremity_high, STRONG_CLV),
    ],
    "SPRING": [
        ("clv", _extremity_high, STRONG_CLV),
    ],
    "UPTHRUST": [
        ("clv", _extremity_low, WEAK_CLV),
    ],
    "ABSORPTION": [
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("spread_pctile", _extremity_high, HIGH_SPREAD_PCTILE),
        ("net_move_z", _extremity_low_bounded, ABSORPTION_MAX_NET_MOVE_Z),
    ],
}

DAILY_TAG_DRIVERS = {
    "NO_SUPPLY": [
        ("spread_pctile", _extremity_low, LOW_SPREAD_PCTILE),
        ("vol_pctile", _extremity_low, LOW_VOL_PCTILE),
    ],
    "NO_DEMAND": [
        ("spread_pctile", _extremity_low, LOW_SPREAD_PCTILE),
        ("vol_pctile", _extremity_low, LOW_VOL_PCTILE),
    ],
    "TEST": [
        ("vol_pctile", _extremity_low, 0.50),
        ("clv", _extremity_high, STRONG_CLV),
    ],
    "SHAKEOUT": [
        ("spread_pctile", _extremity_high, HIGH_SPREAD_PCTILE),
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("clv", _extremity_high, STRONG_CLV),
    ],
    "UPTHRUST": [
        ("spread_pctile", _extremity_high, HIGH_SPREAD_PCTILE),
        ("vol_pctile", _extremity_high, HIGH_VOL_PCTILE),
        ("clv", _extremity_low, WEAK_CLV),
    ],
}


def _tier_tag(df: pd.DataFrame, tag_col: str, drivers: list) -> pd.Series:
    """
    For a boolean/string tag column, computes a companion 3-tier
    classification based on the strength of its continuous drivers.
    Handles SPRING/UPTHRUST's "CONFIRMED"/"PENDING"/False encoding by
    treating anything not equal to False as "fired".
    """
    fired = df[tag_col] != False  # noqa: E712 -- handles "CONFIRMED"/"PENDING" strings too

    strength = pd.Series(0.0, index=df.index)
    for col, extremity_fn, threshold in drivers:
        strength = strength + extremity_fn(df[col], threshold).fillna(0)
    strength = strength / len(drivers)

    tier = pd.Series("NEUTRAL", index=df.index)
    tier[fired & (strength < TIER_MAJOR_THRESHOLD)] = "MINOR_OBSERVATION"
    tier[fired & (strength >= TIER_MAJOR_THRESHOLD)] = "MAJOR_SIGNAL"
    return tier


def apply_weekly_tiering(tagged_df: pd.DataFrame) -> pd.DataFrame:
    df = tagged_df.copy()
    for tag_col, drivers in WEEKLY_TAG_DRIVERS.items():
        df[f"{tag_col}_TIER"] = _tier_tag(df, tag_col, drivers)
    return df


def apply_daily_tiering(tagged_df: pd.DataFrame) -> pd.DataFrame:
    df = tagged_df.copy()
    for tag_col, drivers in DAILY_TAG_DRIVERS.items():
        df[f"{tag_col}_TIER"] = _tier_tag(df, tag_col, drivers)
    return df


if __name__ == "__main__":
    stock_data = ingest_all_stocks()
    passed_data, _ = filter_universe(stock_data)
    weekly_data = build_weekly_dataset(passed_data)
    weekly_tagged = tag_all_tickers(weekly_data)
    daily_tagged = build_daily_tagged_dataset(passed_data, weekly_tagged)

    weekly_tiered = {t: apply_weekly_tiering(df) for t, df in weekly_tagged.items()}
    daily_tiered = {t: apply_daily_tiering(df) for t, df in daily_tagged.items()}

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", None)

    print("=" * 100)
    print("STEP 6: WEEKLY TIER DISTRIBUTION (HDFCBANK) -- counts per tag")
    print("=" * 100)
    if "HDFCBANK" in weekly_tiered:
        h = weekly_tiered["HDFCBANK"]
        rows = []
        for tag in WEEKLY_TAG_DRIVERS:
            counts = h[f"{tag}_TIER"].value_counts()
            rows.append({
                "tag": tag,
                "MAJOR_SIGNAL": counts.get("MAJOR_SIGNAL", 0),
                "MINOR_OBSERVATION": counts.get("MINOR_OBSERVATION", 0),
                "NEUTRAL": counts.get("NEUTRAL", 0),
            })
        print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 100)
    print("STEP 6: DAILY TIER DISTRIBUTION (HDFCBANK) -- counts per tag")
    print("=" * 100)
    if "HDFCBANK" in daily_tiered:
        h = daily_tiered["HDFCBANK"]
        rows = []
        for tag in DAILY_TAG_DRIVERS:
            counts = h[f"{tag}_TIER"].value_counts()
            rows.append({
                "tag": tag,
                "MAJOR_SIGNAL": counts.get("MAJOR_SIGNAL", 0),
                "MINOR_OBSERVATION": counts.get("MINOR_OBSERVATION", 0),
                "NEUTRAL": counts.get("NEUTRAL", 0),
            })
        print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 100)
    print("SPOT CHECK: HDFCBANK weekly SELLING_CLIMAX instances, sorted by tier")
    print("=" * 100)
    if "HDFCBANK" in weekly_tiered:
        h = weekly_tiered["HDFCBANK"]
        fired = h[h["SELLING_CLIMAX"] != False]  # noqa: E712
        cols = ["week_start", "close", "vol_pctile", "spread_pctile", "clv", "SELLING_CLIMAX_TIER"]
        print(fired[cols].sort_values("SELLING_CLIMAX_TIER").to_string(index=False))
