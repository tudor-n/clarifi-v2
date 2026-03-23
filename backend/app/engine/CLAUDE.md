# Data engine — read 03-DATA-ENGINE-SPEC.md before touching anything here

## Inspector pattern
class MyInspector(BaseInspector):
    name = "My Inspector"
    category = "completeness"  # completeness|uniqueness|consistency|accuracy|format
    
    def run(self, df: pl.DataFrame, schema: DatasetSchema) -> list[Issue]:
        # Return Issues — never mutate df
        # Use schema.column_types for type-aware checks
        # affected_cells: only first 100 for performance

## Fixer pattern  
class MyFixer(BaseFixer):
    name = "My Fixer"
    handles_categories = ["format"]
    
    def fix(self, df: pl.DataFrame, issues: list[Issue]) -> FixResult:
        # Return FixResult(clean_df, quarantine_df, changes)
        # Never drop rows — quarantine instead
        # Log every change with row/column/old_value/new_value

## Scoring — don't touch scorer.py directly
The scorer weights are in the spec. Open a discussion before changing weights.

## Performance rules
- All operations must work on 500k row DataFrames
- Use Polars lazy API (.lazy() → .collect()) for multi-step transforms
- Never call .to_pandas() — Polars only