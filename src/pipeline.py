import logging
from pathlib import Path
import pandas as pd

from config import BATCH_FILES, PROPERTIES_FILE, FX_FILE, OUTPUT_DIR, MAX_GUESTS, VALID_STATUSES
from cleaning import clean_bookings, clean_properties, clean_fx
from merge import merge_batches, current_state, audit_batch, flag_latest_timestamp_conflicts
from fx import add_point_in_time_fx
from validation import validation_reasons, data_quality_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def read_batch(path, batch_number, sequence_start=0):
    df = pd.read_csv(path)
    df["_source_file"] = Path(path).name
    df["_source_batch"] = batch_number
    df["_source_row"] = range(1, len(df) + 1)
    df["_source_sequence"] = range(sequence_start, sequence_start + len(df))
    return clean_bookings(df)


def run_pipeline(output_dir=OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    properties = clean_properties(pd.read_csv(PROPERTIES_FILE))
    fx = clean_fx(pd.read_csv(FX_FILE))
    b1 = read_batch(BATCH_FILES[0], 1, 0)
    b2 = read_batch(BATCH_FILES[1], 2, len(b1))
    raw_combined = pd.concat([b1, b2], ignore_index=True)

    conflict_ids = flag_latest_timestamp_conflicts(raw_combined)
    audit_detail, audit_summary = audit_batch(b1, b2)
    current = merge_batches(b1, b2)
    current = add_point_in_time_fx(current, fx)
    current = current.merge(properties, on="property_id", how="left", validate="many_to_one")

    reasons = validation_reasons(
        current,
        set(properties["property_id"]),
        VALID_STATUSES,
        MAX_GUESTS,
        conflict_ids,
    )
    current["reject_reason"] = reasons

    rejects = current[current["reject_reason"].ne("")].copy()
    valid = current[current["reject_reason"].eq("")].copy()

    # Status representation: all valid current-state bookings remain available for audit.
    # Only confirmed bookings count as recognised reporting revenue.
    valid["is_reportable_revenue"] = valid["booking_status"].eq("confirmed")
    valid["reporting_revenue_zar"] = valid["revenue_zar"].where(valid["is_reportable_revenue"], 0.0)

    dq = data_quality_summary(current, raw_combined, set(properties["property_id"]))

    drop_internal = ["_source_sequence"]
    valid.drop(columns=drop_internal, errors="ignore").to_csv(output_dir / "analysis_ready_bookings.csv", index=False)
    rejects.drop(columns=drop_internal, errors="ignore").to_csv(output_dir / "rejects.csv", index=False)
    dq.to_csv(output_dir / "data_quality_summary.csv", index=False)
    audit_summary.to_csv(output_dir / "merge_audit.csv", index=False)
    audit_detail.to_csv(output_dir / "merge_audit_detail.csv", index=False)

    log.info("Raw rows: %s", len(raw_combined))
    log.info("Current-state rows: %s", len(current))
    log.info("Analysis-ready rows: %s", len(valid))
    log.info("Rejected rows: %s", len(rejects))
    log.info("Latest-timestamp conflicts: %s", sorted(conflict_ids))
    return valid, rejects, dq, audit_summary


if __name__ == "__main__":
    run_pipeline()
