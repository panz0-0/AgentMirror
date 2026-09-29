"""Verify path traversal, knowledge download null-check, and generation concurrency guards."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def test_safe_path_utils():
    from app.utils.path_tool import GENERATED_DIR, safe_filename, safe_resolve_under

    assert safe_filename("../../evil.png") == "evil.png"
    assert safe_filename("..") == "file"
    assert safe_filename("") == "file"

    inside = safe_resolve_under(GENERATED_DIR, "abc123", "H1.png")
    assert inside is not None
    assert str(inside).startswith(str(GENERATED_DIR.resolve()))

    escaped = safe_resolve_under(GENERATED_DIR, "..", "H1.png")
    assert escaped is None

    escaped2 = safe_resolve_under(GENERATED_DIR, "job", "..", "..", "knowledge", "secret.pdf")
    assert escaped2 is None
    print("OK path_tool safe helpers")


def test_sku_safe_filename():
    from app.utils.path_tool import safe_filename

    assert safe_filename("../../../tmp/x.png") == "x.png"
    print("OK sku filename sanitization")


async def test_generation_running_guard():
    from app.services import generation_service
    from app.models.sku import GenerationJob

    mock_job = GenerationJob(id="j1", sku_id="sku1", status="running")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_job
    mock_db.execute = AsyncMock(return_value=mock_result)

    found = await generation_service.get_running_job_for_sku(mock_db, "sku1")
    assert found is mock_job
    print("OK get_running_job_for_sku")


async def test_generation_lock_serializes():
    from app.services.generation_service import sku_generation_lock

    order = []

    async def worker(tag):
        async with sku_generation_lock("sku-x"):
            order.append(f"{tag}-in")
            await asyncio.sleep(0.05)
            order.append(f"{tag}-out")

    await asyncio.gather(worker("a"), worker("b"))
    # One worker must fully finish before the other enters
    assert order.index("a-in") < order.index("a-out")
    assert order.index("b-in") < order.index("b-out")
    assert (order[1] == "a-out" and order[2] == "b-in") or (order[1] == "b-out" and order[2] == "a-in")
    print("OK sku_generation_lock serializes concurrent access")


def test_knowledge_download_null_order():
    """Static check: doc must be checked before file_path access."""
    src = (BACKEND / "app" / "router" / "knowledge.py").read_text(encoding="utf-8")
    idx_doc = src.index("doc = await svc.get_doc(doc_id)")
    idx_check = src.index("if not doc:")
    idx_path = src.index("resolve_storage_path(doc.file_path)")
    assert idx_check < idx_path, "null check must precede doc.file_path access"
    print("OK knowledge download null-check order")


async def main():
    test_safe_path_utils()
    test_sku_safe_filename()
    await test_generation_running_guard()
    await test_generation_lock_serializes()
    test_knowledge_download_null_order()
    print("\nALL FIX VERIFICATIONS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
