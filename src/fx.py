import pandas as pd


def add_point_in_time_fx(bookings, fx_rates):
    """Join each booking to the latest FX rate effective on or before created_at."""
    left = bookings.copy().reset_index(drop=False).rename(columns={"index": "_original_index"})
    left["created_date"] = left["created_at"].dt.normalize()
    left["currency"] = left["currency"].astype(str)
    fx = fx_rates.rename(columns={"effective_from": "fx_effective_from"}).copy()
    fx["currency"] = fx["currency"].astype(str)

    # merge_asof requires sorting by the time key globally.
    left_sorted = left.sort_values(["created_date", "currency"])
    fx_sorted = fx.sort_values(["fx_effective_from", "currency"])
    merged = pd.merge_asof(
        left_sorted,
        fx_sorted,
        left_on="created_date",
        right_on="fx_effective_from",
        by="currency",
        direction="backward",
        allow_exact_matches=True,
    )
    merged["revenue_zar"] = merged["revenue"] * merged["rate_to_zar"]
    return (merged.sort_values("_original_index")
            .drop(columns=["_original_index", "created_date"])
            .reset_index(drop=True))
