import pandas as pd

BUSINESS_COLUMNS = [
    "property_id", "check_in", "check_out", "num_guests", "room_rate", "currency",
    "revenue", "booking_channel", "booking_status", "created_at"
]


def flag_latest_timestamp_conflicts(df):
    """Return booking_ids whose latest timestamp has multiple different row versions."""
    max_ts = df.groupby("booking_id")["updated_at"].transform("max")
    latest = df[df["updated_at"].eq(max_ts)].copy()
    latest = latest.drop_duplicates(subset=["booking_id", "updated_at"] + BUSINESS_COLUMNS)
    counts = latest.groupby("booking_id").size()
    return set(counts[counts > 1].index)


def current_state(df):
    """Deterministically keep the latest version per booking_id."""
    work = df.copy()
    # Exact re-sends are harmless and can be removed before ranking.
    dedupe_cols = ["booking_id", "updated_at"] + BUSINESS_COLUMNS
    work = work.drop_duplicates(subset=dedupe_cols, keep="last")
    # Source sequence only breaks fully-tied duplicates deterministically; conflicting
    # latest-timestamp rows are separately surfaced and quarantined by validation.
    work = work.sort_values(["booking_id", "updated_at", "_source_sequence"])
    return work.drop_duplicates("booking_id", keep="last").reset_index(drop=True)


def audit_batch(existing, incoming):
    """Vectorised row-level audit of the incoming batch against the existing current state."""
    import numpy as np

    base = current_state(existing)[["booking_id", "updated_at"] + BUSINESS_COLUMNS].copy()
    audit = incoming[["booking_id", "updated_at"] + BUSINESS_COLUMNS].copy()
    audit = audit.merge(base, on="booking_id", how="left", suffixes=("_incoming", "_existing"), indicator=True)

    same_value = pd.Series(True, index=audit.index)
    for c in BUSINESS_COLUMNS:
        a = audit[f"{c}_incoming"]
        b = audit[f"{c}_existing"]
        same_value &= a.eq(b) | (a.isna() & b.isna())

    is_new = audit["_merge"].eq("left_only")
    newer = audit["updated_at_incoming"] > audit["updated_at_existing"]
    older = audit["updated_at_incoming"] < audit["updated_at_existing"]
    same_ts = audit["updated_at_incoming"].eq(audit["updated_at_existing"] )

    audit["action"] = np.select(
        [is_new, newer, older, same_ts & same_value, same_ts & ~same_value],
        ["inserted", "updated", "stale_ignored", "unchanged", "same_timestamp_conflict"],
        default="unchanged",
    )

    detail = audit[["booking_id", "action", "updated_at_incoming", "updated_at_existing"]].rename(
        columns={"updated_at_incoming": "incoming_updated_at",
                 "updated_at_existing": "existing_updated_at"}
    )
    summary = detail.groupby("action").size().rename("row_count").reset_index()
    return detail, summary


def merge_batches(existing, incoming):
    """Append then select latest by timestamp; stale updates cannot overwrite newer ones."""
    combined = pd.concat([existing, incoming], ignore_index=True)
    return current_state(combined)
