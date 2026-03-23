import polars as pl
from .base import BaseInspector, InspectionResult, Issue


class AccuracyInspector(BaseInspector):
    """
    Checks for outliers and suspicious values in numeric columns.
    Uses the IQR method (Interquartile Range) to detect outliers.
    """
    name = "accuracy"

    def inspect(self, df: pl.DataFrame) -> InspectionResult:
        result = InspectionResult(inspector_name=self.name)

        for column in df.columns:
            if df[column].dtype not in (
                pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                pl.Float32, pl.Float64,
            ):
                continue

            values = df[column].drop_nulls()
            if len(values) < 4:
                continue
            
            q1 = values.quantile(0.25)
            q3 = values.quantile(0.75)
            iqr = q3 - q1

            if iqr == 0:
                continue

            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            outliers = df[column].drop_nulls().filter(
                (pl.col(column) < lower_bound) | (pl.col(column) > upper_bound)
            )

            outlier_count = len(outliers)
            if outlier_count == 0:
                continue

            pct = (outlier_count / len(df)) * 100
            examples = outliers.head(3).cast(pl.String).to_list()

            result.add_issue(Issue(
                column=column,
                issue_type="outliers",
                severity="warning" if pct < 5 else "critical",
                affected_rows=outlier_count,
                total_rows=len(df),
                description=(
                    f"Column '{column}' has {outlier_count} outliers ({pct:.1f}%). "
                    f"Expected range: {lower_bound:.2f} to {upper_bound:.2f}"
                ),
                examples=examples,
            ))

        return result