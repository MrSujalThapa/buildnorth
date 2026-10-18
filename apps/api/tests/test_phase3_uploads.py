import asyncio
from uuid import uuid4

import pytest

from personal_markets.core.errors import ResourceNotFoundError, SemanticProviderError
from personal_markets.evidence.parsers import parse_upload, rows_from_table
from personal_markets.evidence.uploads import UploadService, UploadStore


@pytest.mark.asyncio
async def test_csv_preview_and_mapping_are_deterministic() -> None:
    raw = b"week,subscribers\n2026-01-07,800\n2026-01-14,860\n"
    parsed = parse_upload("subs.csv", raw)
    assert parsed["kind"] == "csv"
    assert parsed["columns"] == ["week", "subscribers"]
    rows = rows_from_table(
        raw,
        "subs.csv",
        {
            "metric": "subscribers",
            "value_column": "subscribers",
            "observed_at_column": "week",
            "observation_kind": "snapshot",
        },
    )
    assert len(rows) == 2
    assert rows[0]["numeric_value"] == 800
    assert rows[0]["source_type"] == "upload"


@pytest.mark.asyncio
async def test_upload_is_owner_scoped_and_deduped() -> None:
    service = UploadService(UploadStore())
    owner = uuid4()
    other = uuid4()
    goal = uuid4()
    raw = b"date,value\n2026-01-01,1\n"
    first = await service.ingest(owner, goal, "a.csv", raw, "text/csv")
    second = await service.ingest(owner, goal, "a.csv", raw, "text/csv")
    assert first.upload_id == second.upload_id
    with pytest.raises(ResourceNotFoundError):
        await service.get(other, first.upload_id)
    assert await service.list_for_goal(other, goal) == []


@pytest.mark.asyncio
async def test_rejects_oversize_and_unknown_types() -> None:
    service = UploadService(UploadStore())
    owner = uuid4()
    goal = uuid4()
    with pytest.raises(SemanticProviderError):
        await service.ingest(owner, goal, "x.exe", b"MZ", "application/octet-stream")
    with pytest.raises(SemanticProviderError):
        await service.ingest(owner, goal, "huge.csv", b"a" * 5_000_001, "text/csv")


@pytest.mark.asyncio
async def test_owner_quota_and_deletion_free_space() -> None:
    service = UploadService(UploadStore(), max_owner_bytes=40)
    owner = uuid4()
    goal = uuid4()
    first = await service.ingest(owner, goal, "a.csv", b"date,value\n2026-01-01,1\n", "text/csv")
    with pytest.raises(SemanticProviderError):
        await service.ingest(owner, goal, "b.csv", b"date,value\n2026-01-02,2\n", "text/csv")
    await service.delete(owner, first.upload_id)
    with pytest.raises(ResourceNotFoundError):
        await service.get(owner, first.upload_id)
    restored = await service.ingest(owner, goal, "a.csv", b"date,value\n2026-01-01,1\n", "text/csv")
    assert restored.upload_id != first.upload_id


@pytest.mark.asyncio
async def test_concurrent_duplicate_ingests_share_one_row() -> None:
    service = UploadService(UploadStore())
    owner = uuid4()
    goal = uuid4()
    raw = b"date,value\n2026-01-01,1\n"
    rows = await asyncio.gather(
        *[service.ingest(owner, goal, "a.csv", raw, "text/csv") for _ in range(8)]
    )
    assert len({item.upload_id for item in rows}) == 1
    assert len(await service.list_for_goal(owner, goal)) == 1


def test_pdf_text_is_untrusted_excerpt() -> None:
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf not installed")
    from io import BytesIO

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    parsed = parse_upload("note.pdf", buffer.getvalue())
    assert parsed["kind"] == "pdf"
    assert parsed["ambiguous"] is True
