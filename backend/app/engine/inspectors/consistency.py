import polars as pl
from .base import BaseInspector, InspectionResult, Issue


class ConsistencyInspector(BaseInspector):
    """
    Checks for mixed formats and inconsistent casing in string columns.
    For example: dates written as both "2024-01-01" and "01/01/2024",
    or names written as both "john" and "John" and "JOHN".
    """
    name = "consistency"

    def inspect(self, df: pl.DataFrame) -> InspectionResult:
        result = InspectionResult(inspector_name=self.name)

        for column in df.columns:
            if df[column].dtype != pl.String:
                continue

            values = df[column].drop_nulls()
            if values.is_empty():
                continue

            self._check_mixed_casing(result, column, values, len(df))
            self._check_mixed_date_formats(result, column, values, len(df))

        return result

    def _check_mixed_casing(
        self,
        result: InspectionResult,
        column: str,
        values: pl.Series,
        total_rows: int,
    ):
        lower_count = values.filter(values == values.str.to_lowercase()).len()
        upper_count = values.filter(values == values.str.to_uppercase()).len()
        title_count = values.filter(values == values.str.to_titlecase()).len()

        styles_present = sum([
            lower_count > len(values) * 0.1,
            upper_count > len(values) * 0.1,
            title_count > len(values) * 0.1,
        ])

        if styles_present >= 2:
            examples = values.sample(min(3, len(values)), seed=42).to_list()
            result.add_issue(Issue(
                column=column,
                issue_type="mixed_casing",
                severity="warning",
                affected_rows=len(values),
                total_rows=total_rows,
                description=f"Column '{column}' has mixed casing styles (e.g. 'john', 'John', 'JOHN')",
                examples=[str(e) for e in examples],
            ))

    def _check_mixed_date_formats(
        self,
        result: InspectionResult,
        column: str,
        values: pl.Series,
        total_rows: int,
    ):
        formats = {
            "YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$",
            "DD/MM/YYYY": r"^\d{2}/\d{2}/\d{4}$",
            "MM-DD-YYYY": r"^\d{2}-\d{2}-\d{4}$",
            "DD-MM-YYYY": r"^\d{2}-\d{2}-\d{4}$",
        }

        detected_formats = []
        for fmt_name, pattern in formats.items():
            matches = values.str.contains(pattern).sum()
            if matches > len(values) * 0.1:
                detected_formats.append(fmt_name)

        if len(detected_formats) >= 2:
            examples = values.sample(min(3, len(values)), seed=42).to_list()
            result.add_issue(Issue(
                column=column,
                issue_type="mixed_date_formats",
                severity="warning",
                affected_rows=len(values),
                total_rows=total_rows,
                description=f"Column '{column}' has mixed date formats: {', '.join(detected_formats)}",
                examples=[str(e) for e in examples],
            ))