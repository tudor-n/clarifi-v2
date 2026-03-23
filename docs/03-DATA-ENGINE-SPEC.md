# 03 — Data Quality Engine Specification

## Architecture: Pipeline Pattern

v1 ran inspectors sequentially, then scoring as one blob. v2 introduces a formal pipeline with profiling first, then inspectors informed by profile, then scoring, then optional LLM enrichment.

```
File Bytes
    │
    ▼
┌─────────┐
│ Reader   │  → Polars DataFrame (with type inference)
└────┬────┘
     │
     ▼
┌──────────┐
│ Profiler  │  → ColumnProfile[] (type, cardinality, nulls, patterns)
└────┬─────┘
     │
     ▼
┌─────────────┐
│ Inspectors   │  → Issue[] (each inspector gets profile + df)
│ (parallel)   │
└────┬────────┘
     │
     ▼
┌─────────┐
│ Scorer   │  → QualityReport (weighted, non-linear)
└────┬────┘
     │
     ▼
┌───────────┐
│ LLM       │  → Enhanced QualityReport (summary + per-column advice)
│ (optional) │
└───────────┘
```

---

## Column Profiler (NEW)

v1 had no explicit column profiling — each inspector independently guessed column types. v2 profiles once, shares everywhere.

```python
# app/engine/profiler.py
from dataclasses import dataclass
from enum import Enum
import polars as pl
import re

class SemanticType(str, Enum):
    ID = "id"
    NAME = "name"
    EMAIL = "email"
    PHONE = "phone"
    DATE = "date"
    BOOLEAN = "boolean"
    CURRENCY = "currency"
    RATING = "rating"
    CATEGORICAL = "categorical"
    NUMERIC = "numeric"
    FREETEXT = "freetext"
    UNKNOWN = "unknown"

@dataclass
class ColumnProfile:
    name: str
    dtype: str                          # Polars dtype
    semantic_type: SemanticType
    null_count: int
    null_rate: float
    unique_count: int
    cardinality_ratio: float            # unique / total (1.0 = all unique)
    sample_values: list[str]            # First 20 non-null values
    inferred_pattern: str | None        # Regex pattern if detected
    stats: dict                         # min, max, mean, std for numeric; mode for categorical

class ColumnProfiler:
    """Profiles every column once. Inspectors and fixers use profiles instead of re-inferring."""

    # Pattern-based semantic type rules (ordered by priority)
    NAME_PATTERNS = {"name", "first", "last", "firstname", "lastname", "fullname", "full_name"}
    EMAIL_PATTERNS = {"email", "mail", "e_mail", "email_address"}
    PHONE_PATTERNS = {"phone", "telephone", "mobile", "cell", "contact"}
    DATE_PATTERNS = {"date", "created", "updated", "dob", "birth", "start", "end", "join", "hire"}
    ID_PATTERNS = {"id", "uid", "uuid", "record_id", "emp_id", "user_id"}
    RATING_PATTERNS = {"rating", "score", "grade", "eval", "stars", "performance"}

    def profile(self, df: pl.DataFrame) -> list[ColumnProfile]:
        profiles = []
        for col_name in df.columns:
            col = df[col_name]
            profiles.append(self._profile_column(col_name, col, df.height))
        return profiles

    def _profile_column(self, name: str, col: pl.Series, total_rows: int) -> ColumnProfile:
        null_count = col.null_count()
        non_null = col.drop_nulls()
        unique_count = non_null.n_unique() if non_null.len() > 0 else 0

        # Semantic type inference: name-based first, then content-based
        sem_type = self._infer_semantic_type(name, col)

        # Stats
        stats = self._compute_stats(col, sem_type)

        return ColumnProfile(
            name=name,
            dtype=str(col.dtype),
            semantic_type=sem_type,
            null_count=null_count,
            null_rate=null_count / max(total_rows, 1),
            unique_count=unique_count,
            cardinality_ratio=unique_count / max(non_null.len(), 1),
            sample_values=[str(v) for v in non_null.head(20).to_list()],
            inferred_pattern=None,
            stats=stats,
        )

    def _infer_semantic_type(self, name: str, col: pl.Series) -> SemanticType:
        """Two-phase inference: column name heuristics, then content analysis."""
        clean_name = name.lower().replace(" ", "_").strip()

        # Phase 1: Name-based (high confidence)
        if clean_name in self.ID_PATTERNS or clean_name.endswith("_id"):
            return SemanticType.ID
        if any(p in clean_name for p in self.EMAIL_PATTERNS):
            return SemanticType.EMAIL
        if any(p in clean_name for p in self.NAME_PATTERNS):
            return SemanticType.NAME
        if any(p in clean_name for p in self.PHONE_PATTERNS):
            return SemanticType.PHONE
        if any(p in clean_name for p in self.DATE_PATTERNS):
            return SemanticType.DATE
        if any(p in clean_name for p in self.RATING_PATTERNS):
            return SemanticType.RATING

        # Phase 2: Content-based
        if col.dtype in (pl.Float32, pl.Float64, pl.Int8, pl.Int16, pl.Int32, pl.Int64):
            return SemanticType.NUMERIC

        if col.dtype == pl.Utf8:
            return self._infer_from_content(col)

        return SemanticType.UNKNOWN

    def _infer_from_content(self, col: pl.Series) -> SemanticType:
        non_null = col.drop_nulls().to_list()
        if len(non_null) < 3:
            return SemanticType.UNKNOWN

        sample = non_null[:200]

        # Email content check
        email_re = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
        if sum(1 for v in sample if email_re.match(str(v).strip())) / len(sample) > 0.5:
            return SemanticType.EMAIL

        # Boolean content check
        bool_vals = {"yes", "no", "true", "false", "1", "0", "y", "n", "t", "f"}
        if all(str(v).strip().lower() in bool_vals for v in sample):
            return SemanticType.BOOLEAN

        # Numeric content check
        numeric_count = sum(1 for v in sample if self._is_numeric(str(v)))
        if numeric_count / len(sample) > 0.7:
            return SemanticType.NUMERIC

        # Low cardinality = categorical
        if len(set(sample)) / len(sample) < 0.1 and len(set(sample)) < 50:
            return SemanticType.CATEGORICAL

        return SemanticType.FREETEXT

    @staticmethod
    def _is_numeric(v: str) -> bool:
        try:
            float(v.strip().replace(",", "").lstrip("$€£¥"))
            return True
        except ValueError:
            return False
```

---

## Inspector Registry (Auto-Discovery)

```python
# app/engine/inspectors/registry.py
from typing import Protocol
import polars as pl
from app.engine.profiler import ColumnProfile

class Inspector(Protocol):
    name: str
    category: str

    def inspect(self, df: pl.DataFrame, profiles: list[ColumnProfile]) -> list[Issue]:
        ...

_REGISTRY: list[type[Inspector]] = []

def register(cls: type[Inspector]) -> type[Inspector]:
    """Decorator to auto-register inspectors."""
    _REGISTRY.append(cls)
    return cls

def get_all_inspectors() -> list[Inspector]:
    return [cls() for cls in _REGISTRY]
```

Usage:
```python
# app/engine/inspectors/completeness.py
from app.engine.inspectors.registry import register

@register
class MissingValuesInspector:
    name = "Missing Values"
    category = "completeness"

    def inspect(self, df: pl.DataFrame, profiles: list[ColumnProfile]) -> list[Issue]:
        issues = []
        for profile in profiles:
            if profile.null_count == 0:
                continue
            # Use profile.semantic_type to set severity:
            # Missing IDs/emails = critical, missing optional text = info
            severity = "critical" if profile.semantic_type in (SemanticType.ID, SemanticType.EMAIL) else \
                       "warning" if profile.null_rate > 0.1 else "info"
            issues.append(Issue(
                inspector_name=self.name,
                category=self.category,
                severity=severity,
                column=[profile.name],
                count=profile.null_count,
                description=f"Column '{profile.name}' has {profile.null_count} missing values ({profile.null_rate:.1%}).",
                suggestion=self._suggest(profile),
                affected_cells=self._get_affected(df, profile.name),
            ))
        return issues

    def _suggest(self, profile: ColumnProfile) -> str:
        if profile.semantic_type == SemanticType.NUMERIC:
            return "Fill with column median or mean."
        if profile.semantic_type == SemanticType.CATEGORICAL:
            return f"Fill with mode (most frequent value)."
        if profile.semantic_type in (SemanticType.ID, SemanticType.EMAIL, SemanticType.NAME):
            return "These values cannot be inferred — manual entry required."
        return "Review and fill or remove rows."
```

---

## Quality Scorer v2

### Problems with v1 Scoring
1. Completeness penalty is overly aggressive (cubic decay `** 1.5`)
2. Uniqueness penalty is harsh (`dup_rate * 2.0`)
3. Issue-driven categories use fixed costs that don't scale with dataset size
4. No normalization — a 10-row dataset with 1 issue scores the same as 10M rows with 1 issue

### v2 Scoring Algorithm

```python
# app/engine/scorer.py

class QualityScorer:
    """
    Scores datasets on a 0-100 scale across 5 categories.
    Uses adaptive penalties that scale with dataset size.
    """

    WEIGHTS = {
        "completeness": 0.25,
        "uniqueness": 0.20,
        "consistency": 0.20,
        "accuracy": 0.20,
        "format": 0.15,
    }

    def score(self, df: pl.DataFrame, profiles: list[ColumnProfile], issues: list[Issue]) -> ScoringResult:
        total_rows = max(df.height, 1)
        total_cols = max(df.width, 1)

        # --- Completeness: based on actual null rates ---
        col_null_rates = [p.null_rate for p in profiles]
        avg_null_rate = sum(col_null_rates) / len(col_null_rates) if col_null_rates else 0
        worst_null_rate = max(col_null_rates, default=0)
        # Weighted: avg matters, but worst column drags score down
        effective_null = 0.6 * avg_null_rate + 0.4 * worst_null_rate
        completeness = max(0, 100 * (1 - effective_null))

        # --- Uniqueness: penalize duplicate rows ---
        dup_count = df.height - df.unique().height
        dup_rate = dup_count / total_rows
        # Soft penalty: 5% dups = ~90 score, 20% dups = ~60 score
        uniqueness = max(0, 100 * (1 - dup_rate * 2))

        # --- Issue-driven categories ---
        issue_penalties = {"consistency": 0.0, "accuracy": 0.0, "format": 0.0}

        for issue in issues:
            cat = issue.category.lower()
            if cat not in issue_penalties:
                continue

            # Adaptive penalty: scales with affected ratio
            affected_ratio = min(1.0, issue.count / total_rows)
            severity_weight = {"critical": 3.0, "warning": 1.5, "info": 0.3}.get(issue.severity, 0.5)

            # Diminishing returns: 10th issue of same type hurts less than 1st
            existing = issue_penalties[cat]
            remaining_room = 100.0 - existing
            penalty = min(remaining_room, severity_weight * affected_ratio * 50 + severity_weight * 2)
            issue_penalties[cat] += penalty

        consistency = max(0, 100 - issue_penalties["consistency"])
        accuracy = max(0, 100 - issue_penalties["accuracy"])
        fmt = max(0, 100 - issue_penalties["format"])

        # --- Weighted final ---
        w = self.WEIGHTS
        final = (
            completeness * w["completeness"]
            + uniqueness * w["uniqueness"]
            + consistency * w["consistency"]
            + accuracy * w["accuracy"]
            + fmt * w["format"]
        )
        final = int(max(0, min(100, round(final))))

        return ScoringResult(
            overall=final,
            categories={
                "completeness": int(round(completeness)),
                "uniqueness": int(round(uniqueness)),
                "consistency": int(round(consistency)),
                "accuracy": int(round(accuracy)),
                "format": int(round(fmt)),
            },
            traffic_light="GREEN" if final >= 80 else "YELLOW" if final >= 50 else "RED",
        )
```

---

## Autofix Engine v2

### Key Improvements Over v1
1. **Fixer registry** — same pattern as inspectors, each fixer is independent
2. **Profile-aware** — fixers use ColumnProfile instead of re-detecting types
3. **Dry-run mode** — generate change list without applying, for user review
4. **Confidence scores** — each fix has a confidence level (high/medium/low)
5. **Quarantine is smarter** — uses profile to determine what's truly unfixable
6. **No mutation in place** — returns new DataFrame + ChangeLog

```python
# app/engine/fixers/base.py
from dataclasses import dataclass

@dataclass
class FixResult:
    df: pl.DataFrame
    changes: list[ChangeRecord]
    quarantine_indices: set[int]

class BaseFixer:
    name: str
    order: int = 50  # Execution order (lower = earlier)

    def fix(self, df: pl.DataFrame, profiles: list[ColumnProfile]) -> FixResult:
        raise NotImplementedError
```

### Fixer Execution Order

| Order | Fixer | Why This Order |
|-------|-------|----------------|
| 10 | WhitespaceFixer | Must run first — affects all downstream parsing |
| 20 | NullSentinelFixer | Convert "N/A", "null", etc. to actual null |
| 30 | NumericCleanerFixer | Remove currency symbols, thousand seps |
| 40 | DateStandardizerFixer | Normalize to ISO 8601 |
| 50 | EmailFixer | Lowercase, domain correction |
| 60 | PhoneFixer | Standardize format |
| 70 | BooleanFixer | Normalize to True/False |
| 80 | RatingFixer | Text→numeric, clamp ranges |
| 85 | TypeCoercionFixer | Mixed text/numeric columns |
| 90 | CrossColumnFixer | Infer emails from names, names from emails |
| 95 | CasingFixer | Title case names, consistent casing |
| 100 | MissingValueFixer | Fill with median/mode (last — needs clean data) |

### Pipeline Orchestrator

```python
# app/engine/pipeline.py
from app.engine.profiler import ColumnProfiler
from app.engine.inspectors.registry import get_all_inspectors
from app.engine.fixers.registry import get_all_fixers
from app.engine.scorer import QualityScorer

def run_analysis_pipeline(
    df: pl.DataFrame,
    filename: str,
    on_progress: Callable[[float, str], None] | None = None,
) -> QualityReport:
    profiler = ColumnProfiler()
    scorer = QualityScorer()

    # 1. Profile
    profiles = profiler.profile(df)
    if on_progress:
        on_progress(0.2, "Profiled columns")

    # 2. Inspect
    all_issues = []
    inspectors = get_all_inspectors()
    for i, inspector in enumerate(inspectors):
        try:
            issues = inspector.inspect(df, profiles)
            all_issues.extend(issues)
        except Exception as e:
            logger.exception(f"Inspector {inspector.name} failed: {e}")
        if on_progress:
            on_progress(0.2 + 0.6 * (i + 1) / len(inspectors), f"Ran {inspector.name}")

    # 3. Score
    result = scorer.score(df, profiles, all_issues)
    if on_progress:
        on_progress(0.9, "Scored")

    return QualityReport(
        dataset_meta=DatasetMeta(filename=filename, total_rows=df.height, total_columns=df.width),
        overall_quality_score=result.overall,
        category_breakdown=result.categories,
        issues=all_issues,
    )


def run_autofix_pipeline(
    df: pl.DataFrame,
    profiles: list[ColumnProfile] | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> AutofixResult:
    if profiles is None:
        profiles = ColumnProfiler().profile(df)

    all_changes: list[ChangeRecord] = []
    quarantine_indices: set[int] = set()

    fixers = sorted(get_all_fixers(), key=lambda f: f.order)
    for i, fixer in enumerate(fixers):
        try:
            result = fixer.fix(df, profiles)
            df = result.df
            all_changes.extend(result.changes)
            quarantine_indices |= result.quarantine_indices
        except Exception as e:
            logger.exception(f"Fixer {fixer.name} failed: {e}")
        if on_progress:
            on_progress((i + 1) / len(fixers), f"Applied {fixer.name}")

    # Split into clean + quarantine
    if quarantine_indices:
        q_mask = pl.Series([i in quarantine_indices for i in range(df.height)])
        quarantine_df = df.filter(q_mask)
        clean_df = df.filter(~q_mask)
    else:
        clean_df = df
        quarantine_df = df.clear()

    return AutofixResult(
        clean_df=clean_df,
        quarantine_df=quarantine_df,
        changes=all_changes,
    )
```

---

## New Inspectors for v2

| Inspector | Category | What It Catches |
|-----------|----------|----------------|
| `StatisticalOutlierInspector` | accuracy | IQR-based (more robust than v1's 3σ) |
| `CardinalityAnomalyInspector` | consistency | Column with 99% unique values that should be categorical |
| `CrossColumnConsistencyInspector` | consistency | State doesn't match zip code, age < 0, etc. |
| `EncodingIssueInspector` | format | Mojibake, mixed encodings within a column |
| `TemporalOrderInspector` | accuracy | `start_date` > `end_date`, `hire_date` in the future |
| `DomainValueInspector` | accuracy | Country codes not in ISO 3166, currencies not in ISO 4217 |

---

## Performance Targets

| Metric | Target | v1 Actual |
|--------|--------|-----------|
| 10k rows analysis | < 2s | ~3s |
| 100k rows analysis | < 10s | Timeout |
| 500k rows analysis | < 45s | N/A (50k cap) |
| Autofix 10k rows | < 3s | ~5s |
| Autofix 100k rows | < 15s | Timeout |
| Memory per 100k rows | < 500MB | Uncontrolled |

Key optimization techniques:
- Use Polars expressions instead of Python loops wherever possible
- Profile once, share everywhere (no redundant type inference)
- Lazy evaluation with `scan_csv` for large files
- Chunked processing for files > 100k rows
- Redis caching of analysis results (keyed by file hash)
