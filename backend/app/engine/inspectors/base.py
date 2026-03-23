from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import polars as pl


@dataclass
class Issue:
    column: str
    issue_type: str
    severity: str
    affected_rows: int
    total_rows: int
    description: str
    examples: list = field(default_factory=list)

    @property
    def affected_percentage(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return round((self.affected_rows / self.total_rows) * 100, 2)


@dataclass
class InspectionResult:
    inspector_name: str
    issues: list[Issue] = field(default_factory=list)
    passed: bool = True

    def add_issue(self, issue: Issue):
        self.issues.append(issue)
        self.passed = False


class BaseInspector(ABC):
    name: str = "base"

    def __call__(self, df: pl.DataFrame) -> InspectionResult:
        return self.inspect(df)

    @abstractmethod
    def inspect(self, df: pl.DataFrame) -> InspectionResult:
        pass