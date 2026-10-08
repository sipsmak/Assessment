# Data Engineer Assessment

## Overview
This project builds a re-runnable local pipeline for the two booking batches, produces a current-state analysis-ready dataset, quarantines bad records, performs point-in-time FX enrichment, and supplies the requested BigQuery-compatible SQL and production write-up.

The design separates source/history concerns from the reporting layer. Coming from a Data Vault background, I treat `booking_id` as the business key, preserve source changes for auditability, derive the latest trusted business state downstream, and expose a simpler analysis-ready structure for reporting.

## Project structure
- `src/` - cleaning, merge/idempotency, FX, validation and pipeline modules
- `tests/` - pytest unit tests
- `sql/part_a.sql` - Part A BigQuery-compatible SQL
- `data/input/` - supplied CSV files
- `data/output/` - generated artefacts
- `PART_C.md` - one-page production approach
- `OUTPUT_SUMMARY.md` - summary of the executed local results

## Assumptions and decisions
- `booking_id` is the business key and `updated_at` determines recency.
- Historical/re-sent source rows are not treated as a reason to overwrite a newer current state.
- Exact re-sent rows are handled safely and do not create duplicate current records.
- A stale update never replaces a newer current record.
- If two different latest records have the same `booking_id` and `updated_at`, the source does not provide enough information to know which is correct. The booking is therefore quarantined rather than silently choosing a value. In production I would prefer an additional source sequence, load timestamp or ingestion identifier as a deterministic tie-breaker.
- Currency values and symbols are standardised to USD/EUR/GBP/ZAR. Unsupported currencies are rejected.
- Channels are standardised to `direct`, `ota`, `website`, and `travel_agent`.
- The `S. Africa` property value is normalised to `South Africa`.
- `num_guests > 20` is treated as implausible for this lodge/hotel extract and quarantined. This threshold is configuration rather than hard-coded transformation logic and would normally be agreed with the business.
- Pending and cancelled bookings remain in the current-state analysis-ready output because their state is analytically useful. `is_reportable_revenue` is true only for confirmed bookings, and `reporting_revenue_zar` is zero for pending/cancelled bookings.
- FX uses the latest `effective_from` date on or before the booking's `created_at` date, as required in the brief.
- Monthly reporting in Part A is based on `check_in` month, representing the stay/revenue period. This is documented so the metric grain is explicit.

## Run
From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/pipeline.py
```

Outputs are written to `data/output/`:
- `analysis_ready_bookings.csv`
- `rejects.csv`
- `data_quality_summary.csv`
- `merge_audit.csv`
- `merge_audit_detail.csv`
- `monthly_revenue_growth_2025.csv`
- `top_2_properties_by_country.csv`

## Test
```bash
pytest -q
```

The tests cover:
- merge/idempotency
- stale-update protection
- point-in-time FX
- cleaning/standardisation
- validation/quarantine rules

## Output artefacts

### `analysis_ready_bookings.csv`
Contains one trusted current version per valid booking, enriched with property information, point-in-time FX and ZAR revenue values.

### `rejects.csv`
Contains quarantined records with explicit reject reasons instead of silently dropping them.

### `data_quality_summary.csv`
Provides counts for the main data-quality issues surfaced during processing.

### `merge_audit.csv` / `merge_audit_detail.csv`
Shows how the incremental batch was handled, including inserted, updated, unchanged/re-sent and stale records.

## SQL
`sql/part_a.sql` contains the BigQuery-compatible solution for Part A, including:
- current-version resolution
- point-in-time FX conversion
- partitioned/clustered reporting model
- reusable reporting view
- month-on-month confirmed revenue growth
- top properties within country
- raw-level data-quality assertions

The reporting model is deliberately simpler than a Data Vault integration layer. The historical layer preserves change; the reporting layer exposes a trusted current state that analysts can use without rebuilding Hub/Link/Satellite-style joins and latest-record logic.

## AI usage
I used AI to help write the code for this assessment. I first worked through the required logic and defined how I wanted the solution to behave, including the current-record logic, stale-update handling, point-in-time FX matching, validation rules and reporting requirements.

I then prompted AI to translate that logic into SQL and Python code. After the code was generated, I reviewed it, checked that it matched the intended logic, ran the pipeline and automated tests, and adjusted the implementation where necessary.

AI was therefore used mainly to speed up code generation and structure the solution, while the underlying approach, business rules and final review of the implementation were based on my understanding of the assessment requirements.

## Production considerations
For a production GCP implementation, I would land immutable source extracts first, then validate, stage and incrementally merge them into BigQuery. Reporting tables would be partitioned and clustered around expected access patterns, with quality gates before trusted reporting data is published. Scheduling, monitoring, CI/CD, lineage and documented recovery procedures are described in `PART_C.md`.
