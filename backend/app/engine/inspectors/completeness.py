import polars as pl
from .base import BaseInspector, InspectionResult, Issue


class CompletenessInspector(BaseInspector):

    name = "completeness"

    def inspect(self, df: pl.DataFrame) -> InspectionResult:
        result = InspectionResult(inspector_name=self.name)
        total_rows = len(df)

        for column in df.columns:
            null_count = df[column].null_count()

            if null_count == 0:
                continue

            null_indices = (
                df.with_row_index()
                .filter(pl.col(column).is_null())
                .get_column("index")
                .to_list()[:3]
            )

            pct = (null_count / total_rows) * 100
            if pct >= 50:
                severity = "critical"
            elif pct >= 20:
                severity = "warning"
            else:
                severity = "info"

            result.add_issue(Issue(
                column=column,
                issue_type="missing_values",
                severity=severity,
                affected_rows=null_count,
                total_rows=total_rows,
                description=f"Column '{column}' has {null_count} missing values ({pct:.1f}%)",
                examples=[f"row {i}" for i in null_indices],
            ))

        return result