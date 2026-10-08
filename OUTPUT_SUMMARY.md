# Executed output summary

The local pipeline was executed against the supplied CSVs. It read **305 raw rows**, resolved them to **282 current booking IDs**, quarantined **8 current records**, and produced **274 analysis-ready rows**. Re-running the pipeline produces the same current-state result.

The batch-2 merge audit records **19 inserted**, **15 updated**, **5 unchanged/re-sent**, and **1 stale row ignored**. The stale row does not overwrite the newer booking version.

The current-state quality checks surface: **1 unknown property**, **3 non-positive/missing revenue rows**, **2 invalid stay date ranges**, **1 missing FX mapping**, **1 implausible guest count**, and **1 conflicting latest-timestamp booking**. The conflicting record is quarantined because `updated_at` alone cannot identify a trustworthy winner.

Reporting revenue deliberately includes only `confirmed` bookings. Pending and cancelled bookings remain in the analysis-ready current-state table for auditability but have `reporting_revenue_zar = 0`. The executed Part A result extracts are in `data/output/monthly_revenue_growth_2025.csv` and `data/output/top_2_properties_by_country.csv`.
