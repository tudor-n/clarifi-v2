import polars as pl
from .base import BaseInspector, InspectionResult, Issue

class UniquenessInspector(BaseInspector):

    name="uniqueness"

    def inspect(self, df:pl.DataFrame) ->InspectionResult:
        
        result = InspectionResult(inspector_name=self.name)
        total_rows = len(df)


        duplicate_row_count=total_rows - df.unique().height
        if duplicate_row_count>0:

            pct=(duplicate_row_count/total_rows)*100
            result.add_issue(Issue(
                column="[all columns]",
                issues_type="duplicate_row",
                severity="critical" if pct>=10 else "warning",
                affected_rows=duplicate_row_count,
                total_rows=total_rows,
                description=f"{duplicate_row_count} fully duplicate rows found ({pct:.1f}%)",
                examples=[],
            ))
        
        return result