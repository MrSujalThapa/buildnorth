import csv
import io
from typing import Any

from pydantic import BaseModel


class CsvPreview(BaseModel):
    columns: list[str]
    sample_rows: list[dict[str, str]]
    row_count: int


class CsvColumnMapping(BaseModel):
    event_type: str | None = None
    domain: str | None = None
    metric: str
    numeric_value: str | None = None
    categorical_value: str | None = None
    unit: str | None = None
    observed_at: str | None = None
    summary: str | None = None


class CsvImportRequest(BaseModel):
    mapping: CsvColumnMapping
    default_event_type: str = "log"
    default_domain: str = "general"
    default_unit: str | None = None


def preview_csv(raw: str, limit: int = 8) -> CsvPreview:
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV is missing a header row")
    columns = [name.strip() for name in reader.fieldnames if name and name.strip()]
    if not columns:
        raise ValueError("CSV header is empty")
    rows: list[dict[str, str]] = []
    total = 0
    for row in reader:
        total += 1
        if len(rows) < limit:
            rows.append({key: (value or "").strip() for key, value in row.items() if key})
    return CsvPreview(columns=columns, sample_rows=rows, row_count=total)


def parse_csv(raw: str, request: CsvImportRequest) -> list[dict[str, Any]]:
    preview = preview_csv(raw, limit=10_000)
    mapping = request.mapping
    if mapping.metric not in preview.columns:
        raise ValueError("metric column is required and must exist in the CSV")
    records: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(raw))
    for index, row in enumerate(reader, start=2):
        metric = (row.get(mapping.metric) or "").strip()
        if not metric:
            raise ValueError(f"row {index} is missing metric '{mapping.metric}'")
        numeric_raw = (
            (row.get(mapping.numeric_value) or "").strip() if mapping.numeric_value else ""
        )
        numeric_value: float | None = None
        if numeric_raw:
            try:
                numeric_value = float(numeric_raw)
            except ValueError as error:
                raise ValueError(f"row {index} has a non-numeric value") from error
        categorical = (
            (row.get(mapping.categorical_value) or "").strip() if mapping.categorical_value else ""
        )
        if numeric_value is None and not categorical:
            categorical = metric
        records.append(
            {
                "event_type": _cell(row, mapping.event_type) or request.default_event_type,
                "domain": _cell(row, mapping.domain) or request.default_domain,
                "metric": mapping.metric,
                "numeric_value": numeric_value,
                "categorical_value": categorical or None,
                "unit": _cell(row, mapping.unit) or request.default_unit,
                "observed_at": _cell(row, mapping.observed_at) or "unknown",
                "source_type": "csv",
                "summary": _cell(row, mapping.summary) or metric,
            }
        )
    return records


def _cell(row: dict[str, str | None], column: str | None) -> str | None:
    if not column:
        return None
    value = (row.get(column) or "").strip()
    return value or None
