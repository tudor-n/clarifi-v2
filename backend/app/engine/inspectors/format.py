import polars as pl
from .base import BaseInspector, InspectionResult, Issue


class FormatInspector(BaseInspector):
    """
    Checks for invalid formats in columns that look like
    emails, phone numbers, or dates.
    """
    name = "format"

    # Regex patterns
    EMAIL_PATTERN = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    PHONE_PATTERN = r"^\+?[\d\s\-\(\)]{7,15}$"
    DATE_PATTERNS = [
        r"^\d{4}-\d{2}-\d{2}$",        # YYYY-MM-DD
        r"^\d{2}/\d{2}/\d{4}$",        # DD/MM/YYYY
        r"^\d{2}-\d{2}-\d{4}$",        # DD-MM-YYYY
    ]

    # Keywords that hint at what a column contains
    EMAIL_HINTS = ["email", "e-mail", "mail"]
    PHONE_HINTS = ["phone", "mobile", "tel", "contact"]
    DATE_HINTS  = ["date", "dob", "birthday", "created", "updated"]

    def inspect(self, df: pl.DataFrame) -> InspectionResult:
        result = InspectionResult(inspector_name=self.name)

        for column in df.columns:
            if df[column].dtype != pl.String:
                continue

            col_lower = column.lower()
            values = df[column].drop_nulls()

            if values.is_empty():
                continue

            # check based on column name hints
            if any(hint in col_lower for hint in self.EMAIL_HINTS):
                self._check_pattern(
                    result, column, values, len(df),
                    pattern=self.EMAIL_PATTERN,
                    issue_type="invalid_email",
                    description_template="Column '{col}' has {count} invalid email addresses ({pct:.1f}%)",
                )

            elif any(hint in col_lower for hint in self.PHONE_HINTS):
                self._check_pattern(
                    result, column, values, len(df),
                    pattern=self.PHONE_PATTERN,
                    issue_type="invalid_phone",
                    description_template="Column '{col}' has {count} invalid phone numbers ({pct:.1f}%)",
                )

            elif any(hint in col_lower for hint in self.DATE_HINTS):
                self._check_date_column(result, column, values, len(df))

        return result

    def _check_pattern(
        self,
        result: InspectionResult,
        column: str,
        values: pl.Series,
        total_rows: int,
        pattern: str,
        issue_type: str,
        description_template: str,
    ):
        invalid = values.filter(~values.str.contains(pattern))
        invalid_count = len(invalid)

        if invalid_count == 0:
            return

        pct = (invalid_count / total_rows) * 100
        result.add_issue(Issue(
            column=column,
            issue_type=issue_type,
            severity="critical" if pct >= 20 else "warning",
            affected_rows=invalid_count,
            total_rows=total_rows,
            description=description_template.format(
                col=column, count=invalid_count, pct=pct
            ),
            examples=invalid.head(3).to_list(),
        ))

    def _check_date_column(
        self,
        result: InspectionResult,
        column: str,
        values: pl.Series,
        total_rows: int,
    ):
        # a value is valid if it matches ANY of the date patterns
        valid_mask = pl.Series([False] * len(values))
        for pattern in self.DATE_PATTERNS:
            valid_mask = valid_mask | values.str.contains(pattern)

        invalid_count = (~valid_mask).sum()

        if invalid_count == 0:
            return

        pct = (invalid_count / total_rows) * 100
        examples = values.filter(~valid_mask).head(3).to_list()

        result.add_issue(Issue(
            column=column,
            issue_type="invalid_date",
            severity="critical" if pct >= 20 else "warning",
            affected_rows=invalid_count,
            total_rows=total_rows,
            description=f"Column '{column}' has {invalid_count} invalid date values ({pct:.1f}%)",
            examples=examples,
        ))