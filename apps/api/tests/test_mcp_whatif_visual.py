"""The eight MCP visual envelopes use the existing What If engine without writes."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from PIL import Image

from personal_markets.remote_mcp.whatif_image import render_whatif_mobile_png
from remote_mcp_support import McpHarness, create_hiring_goal, structured


async def _render(payload: dict[str, object]) -> bytes:
    if os.name != "nt":
        return await render_whatif_mobile_png(payload)
    script = (
        "import asyncio,json,sys;"
        "from personal_markets.remote_mcp.whatif_image import render_whatif_mobile_png;"
        "sys.stdout.buffer.write(asyncio.run(render_whatif_mobile_png(json.load(sys.stdin))))"
    )
    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", script],
        input=json.dumps(payload).encode(),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return completed.stdout


@pytest.mark.asyncio
async def test_eight_mode_depth_results_preserve_published_receipts() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        evidence = await harness.call(
            grant.access_token,
            "submit_structured_evidence",
            {
                "goal_id": goal_id,
                "metric": "applications",
                "value": 8,
                "unit": "count",
                "observation_kind": "snapshot",
                "observed_at": datetime.now(UTC).isoformat(),
                "idempotency_key": "mcp-whatif-pricing-01",
                "source_category": "job_board",
            },
        )
        assert structured(evidence)["publication"]["priced"] is True
        deps = harness.app.state.agent_workflow._inner._deps
        history_before = await deps.baseline_forecasts.published_history(UUID(goal_id))
        receipt_ids = [item.material_hash for item in history_before]

        for mode in ("impact", "futures", "compare", "paths"):
            for view in ("simple", "deep"):
                question = (
                    "What if I submit 5 additional applications each week?"
                    if mode == "impact"
                    else "What if I focus my job search on FDE roles?"
                )
                result = await harness.call(
                    grant.access_token,
                    "show_what_if_visualization",
                    {
                        "goal_id": goal_id,
                        "mode": mode,
                        "view": view,
                        "question": question,
                        "target_probability": 0.7,
                        "request_id": f"{mode}-{view}",
                    },
                )
                assert result.is_error is False, structured(result)
                payload = structured(result)
                assert payload["kind"] == "playitout_what_if"
                assert payload["goal"]["goal_id"] == goal_id
                assert payload["mode"] == mode and payload["view"] == view
                assert payload["request_id"] == f"{mode}-{view}"
                assert payload["history"]
                assert all(
                    item["source_kind"] == "published_forecast" for item in payload["history"]
                )
                assert payload["baseline"]["priced"] is True
                assert payload[
                    {
                        "impact": "scenario",
                        "futures": "futures",
                        "compare": "comparison",
                        "paths": "targetSearch",
                    }[mode]
                ]
                png = await _render(payload)
                with Image.open(BytesIO(png)) as rendered:
                    assert rendered.size[0] == 1170
                    assert rendered.size[1] >= 900
                if os.environ.get("PM_MCP_SCREENSHOTS") == "1":
                    folder = Path(".artifacts/mcp-whatif")
                    await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
                    await asyncio.to_thread((folder / f"{mode}-{view}.png").write_bytes, png)

        history_after = await deps.baseline_forecasts.published_history(UUID(goal_id))
        assert [item.material_hash for item in history_after] == receipt_ids

        custom = structured(
            await harness.call(
                grant.access_token,
                "show_what_if_visualization",
                {
                    "goal_id": goal_id,
                    "mode": "compare",
                    "view": "simple",
                    "question": "Compare these approaches",
                    "alternatives": [
                        "Apply to 10 jobs per week",
                        "Apply to 5 jobs per week",
                        "Cold email recruiters",
                    ],
                },
            )
        )
        assert len(custom["comparison"]["paths"]) == 3
        assert custom["comparison"]["paths"][2]["primary_goal_probability"] is None

        unsupported = structured(
            await harness.call(
                grant.access_token,
                "show_what_if_visualization",
                {
                    "goal_id": goal_id,
                    "mode": "impact",
                    "question": "What if I cold email recruiters and study LeetCode?",
                },
            )
        )
        assert unsupported["state"] == "unpriced"
        assert "scenario" not in unsupported
        assert unsupported["history"]

        missing_goal = await harness.call(
            grant.access_token,
            "show_what_if_visualization",
            {
                "goal_id": str(uuid4()),
                "mode": "impact",
                "question": "What if I submit 5 additional applications each week?",
            },
        )
        assert missing_goal.is_error is True

        if os.name != "nt":
            image_result = await harness.call(
                grant.access_token,
                "get_what_if_visualization_image",
                {
                    "goal_id": goal_id,
                    "mode": "impact",
                    "view": "simple",
                    "question": "What if I submit 5 additional applications each week?",
                },
            )
            assert image_result.is_error is False
            assert any(
                item.type == "image" and item.mime_type == "image/png"
                for item in image_result.content
            )
            assert structured(image_result)["public_url"] is None
