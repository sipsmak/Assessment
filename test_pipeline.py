import pandas as pd
from pandas.testing import assert_frame_equal

from cleaning import clean_bookings
from merge import merge_batches, current_state
from fx import add_point_in_time_fx
from validation import validation_reasons


def make_rows(rows):
    df = pd.DataFrame(rows)
    defaults = {
        "property_id": "P001", "check_in": "2025-08-01", "check_out": "2025-08-02",
        "num_guests": 2, "room_rate": 100, "currency": "USD", "revenue": "100",
        "booking_channel": " Direct ", "booking_status": "confirmed",
        "created_at": "2025-06-01 00:00:00",
    }
    for c, v in defaults.items():
        if c not in df: df[c] = v
    df["_source_sequence"] = range(len(df))
    return clean_bookings(df)


def test_merge_keeps_newest_and_is_idempotent():
    old = make_rows([{"booking_id": "B1", "updated_at": "2025-06-01", "revenue": "100"}])
    incoming = make_rows([
        {"booking_id": "B1", "updated_at": "2025-06-05", "revenue": "150"},
        {"booking_id": "B2", "updated_at": "2025-06-05", "revenue": "200"},
    ])
    incoming["_source_sequence"] += 10
    once = merge_batches(old, incoming)
    twice = merge_batches(once, incoming)
    assert once.set_index("booking_id").loc["B1", "revenue"] == 150
    assert len(once) == 2
    cols = sorted(c for c in once.columns if c != "_source_sequence")
    assert_frame_equal(once[cols].sort_values("booking_id").reset_index(drop=True),
                       twice[cols].sort_values("booking_id").reset_index(drop=True))


def test_stale_update_does_not_overwrite_newer_value():
    current = make_rows([{"booking_id": "B1", "updated_at": "2025-06-10", "revenue": "500"}])
    stale = make_rows([{"booking_id": "B1", "updated_at": "2025-06-05", "revenue": "100"}])
    stale["_source_sequence"] += 10
    result = merge_batches(current, stale)
    assert result.iloc[0]["revenue"] == 500


def test_point_in_time_fx_uses_rate_effective_on_created_date():
    bookings = make_rows([
        {"booking_id": "B1", "updated_at": "2025-06-01", "created_at": "2025-06-15", "revenue": "100"},
        {"booking_id": "B2", "updated_at": "2025-08-01", "created_at": "2025-07-15", "revenue": "100"},
    ])
    fx = pd.DataFrame({
        "currency": ["USD", "USD"],
        "rate_to_zar": [18.5, 19.0],
        "effective_from": pd.to_datetime(["2025-01-01", "2025-07-01"]),
    })
    result = add_point_in_time_fx(bookings, fx).set_index("booking_id")
    assert result.loc["B1", "revenue_zar"] == 1850
    assert result.loc["B2", "revenue_zar"] == 1900


def test_cleaning_standardises_currency_channel_and_dates():
    df = make_rows([{"booking_id": "B1", "updated_at": "2025-06-01",
                     "currency": " £ ", "booking_channel": "Travel  Agent",
                     "check_in": "21/02/2025", "check_out": "3 Mar 2025"}])
    assert df.iloc[0]["currency"] == "GBP"
    assert df.iloc[0]["booking_channel"] == "travel_agent"
    assert df.iloc[0]["check_in"] == pd.Timestamp("2025-02-21")


def test_validation_rejects_bad_date_and_nonpositive_revenue():
    df = make_rows([{"booking_id": "B1", "updated_at": "2025-06-01",
                     "check_in": "2025-08-05", "check_out": "2025-08-01", "revenue": "0"}])
    df["rate_to_zar"] = 18.5
    reasons = validation_reasons(df, {"P001"}, {"confirmed", "pending", "cancelled"}, 20)
    assert "check_out must be after check_in" in reasons.iloc[0]
    assert "revenue must be positive" in reasons.iloc[0]
