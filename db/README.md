# SQL Performance Governance

Use `sql_performance_governance.sql` as the baseline checklist for:
- index hygiene on hot joins
- materialized view refresh sequence
- periodic EXPLAIN ANALYZE capture
- ANALYZE statistics refresh

Recommended operating routine:
1. Run refresh sequence nightly.
2. Capture EXPLAIN outputs weekly and compare plan/runtime drift.
3. Re-run `ANALYZE` after large data loads.
4. Apply index changes in staging first, then production.
