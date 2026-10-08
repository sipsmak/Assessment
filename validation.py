import pandas as pd


def validation_reasons(df, valid_property_ids, valid_statuses, max_guests, conflict_ids=None):
    """Return one pipe-delimited reject reason string per row."""
    conflict_ids = conflict_ids or set()
    reason = pd.Series("", index=df.index, dtype="string")

    def add(mask, message):
        nonlocal reason
        reason = reason.mask(mask & reason.eq(""), message)
        reason = reason.mask(mask & reason.ne("") & ~reason.str.contains(message, regex=False), reason + " | " + message)

    add(df["booking_id"].isna() | df["booking_id"].eq(""), "missing booking_id")
    add(df["property_id"].isna() | ~df["property_id"].isin(valid_property_ids), "unknown property_id")
    add(df["check_in"].isna() | df["check_out"].isna(), "invalid/missing stay date")
    add(df["check_in"].notna() & df["check_out"].notna() & (df["check_out"] <= df["check_in"]), "check_out must be after check_in")
    add(df["created_at"].isna() | df["updated_at"].isna(), "invalid/missing audit timestamp")
    add(df["updated_at"].notna() & df["created_at"].notna() & (df["updated_at"] < df["created_at"]), "updated_at before created_at")
    add(df["revenue"].isna() | (df["revenue"] <= 0), "revenue must be positive")
    add(df["room_rate"].isna() | (df["room_rate"] <= 0), "room_rate must be positive")
    add(df["num_guests"].isna() | (df["num_guests"] <= 0), "num_guests must be positive")
    add(df["num_guests"].notna() & (df["num_guests"] > max_guests), f"num_guests exceeds {max_guests}")
    add(~df["booking_status"].isin(valid_statuses), "invalid booking_status")
    add(df["rate_to_zar"].isna(), "no applicable FX rate")
    add(df["booking_id"].isin(conflict_ids), "conflicting latest rows share updated_at")
    return reason.str.strip(" |")


def data_quality_summary(current_with_reasons, raw_combined, valid_property_ids):
    checks = [
        ("raw_rows", len(raw_combined)),
        ("raw_duplicate_booking_id_rows", int(raw_combined["booking_id"].duplicated(keep=False).sum())),
        ("current_rows", len(current_with_reasons)),
        ("current_duplicate_booking_ids", int(current_with_reasons["booking_id"].duplicated().sum())),
        ("reject_rows", int(current_with_reasons["reject_reason"].ne("").sum())),
        ("unknown_property_rows", int((~current_with_reasons["property_id"].isin(valid_property_ids)).sum())),
        ("non_positive_or_missing_revenue_rows", int((current_with_reasons["revenue"].isna() | (current_with_reasons["revenue"] <= 0)).sum())),
        ("invalid_date_range_rows", int((current_with_reasons["check_in"].notna() & current_with_reasons["check_out"].notna() & (current_with_reasons["check_out"] <= current_with_reasons["check_in"])).sum())),
        ("missing_fx_rows", int(current_with_reasons["rate_to_zar"].isna().sum())),
        ("implausible_guest_count_rows", int(current_with_reasons["reject_reason"].str.contains("num_guests exceeds", regex=False).sum())),
        ("conflicting_latest_timestamp_rows", int(current_with_reasons["reject_reason"].str.contains("conflicting latest rows", regex=False).sum())),
    ]
    return pd.DataFrame(checks, columns=["check", "row_count"])
