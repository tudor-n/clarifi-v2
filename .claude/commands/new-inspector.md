Create a new data quality inspector.

Before writing code:
1. Read backend/app/engine/inspectors/base.py for the BaseInspector interface
2. Read backend/app/engine/inspectors/completeness.py as a reference implementation
3. Read the inspector section of @docs/03-DATA-ENGINE-SPEC.md

Then create:
- backend/app/engine/inspectors/$ARGUMENTS.py (the inspector)
- backend/tests/unit/test_$ARGUMENTS.py (tests: empty df, all-null, 500k rows, edge cases)
- Register it in backend/app/engine/inspectors/registry.py

The inspector must: return Issues (never mutate df), include affected_cells (max 100), work with Polars lazy API.
