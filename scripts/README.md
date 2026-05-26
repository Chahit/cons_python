# scripts/

One-off maintenance and diagnostic scripts used during development.
These are **not** part of the production application — they have been moved
here from the root directory to keep the project root clean.

| File | Original purpose |
|------|-----------------|
| `_patch_health.py` | Applied health score v2 → v3 weight update |
| `_patch_p360.py` | Partner 360 tab UI patch (first pass) |
| `_patch_p360_v2.py` | Partner 360 tab UI patch (second pass) |
| `_patch_spin.py` | Spinner/loading animation patch |
| `_spin_new.py` | Replacement spinner component experiment |
| `_fix_p360.py` | Bug fix for partner 360 cluster label rendering |
| `_fix_p360_v2.py` | Follow-up fix for partner 360 after v2 redesign |
| `_fix_final.py` | Final pre-demo stability fix |
| `_check_view.py` | Quick sanity-check for DB materialized view schema |
| `change_bg.py` | Utility to swap Streamlit background CSS |
| `diagnose.py` | Prints engine state for debugging startup failures |
| `diagnose_revenue.py` | Dumps partner revenue summary from DB for inspection |

> **Do not import these files.** They were applied once and their changes
> are already baked into the source code.
