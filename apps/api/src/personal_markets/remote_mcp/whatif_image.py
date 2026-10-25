"""Private mobile PNG export of the same bundled React What If component."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.async_api import async_playwright

_RESOURCE = Path(__file__).with_name("whatif_app.html")
_EXPORT_STYLE = """
  html, body, #root { width: 390px !important; margin: 0 !important; overflow-x: hidden; }
  body { background: #f4f2ee; }
  .mcp-what-if-controls, .mcp-what-if .composer, .mcp-what-if .tune-panel,
  .mcp-what-if .option-picker, .mcp-what-if .target-row button,
  .mcp-what-if .metric-row button, .mcp-what-if .what-if-market-chart button,
  .mcp-what-if .path-detail > button, .mcp-what-if .fan-support + article button
  { display: none !important; }
  .mcp-what-if, .mcp-what-if .what-if-shell { min-height: 0 !important; }
  .mcp-what-if .what-if-shell { padding: 18px !important; width: 390px !important; }
  .mcp-what-if h1 { font-size: 25px; line-height: 1.15; margin: 10px 0; }
  .mcp-what-if-heading { margin-bottom: 16px; }
  .mcp-what-if-heading p { font-size: 13px; line-height: 1.4; }
  .mcp-what-if .impact-workspace, .mcp-what-if .deep-primary,
  .mcp-what-if .deep-secondary { display: block !important; }
  .mcp-what-if .deep-primary, .mcp-what-if .viz-block { min-height: 0 !important; }
  .mcp-what-if .viz-block, .mcp-what-if .result-panel,
  .mcp-what-if .quiet-panel { width: 100% !important; max-width: 100% !important; }
  .mcp-what-if .path-annotations button { border: 0; background: transparent; padding: 0; }
"""


async def render_whatif_mobile_png(payload: dict[str, Any]) -> bytes:
    """Render only an owner-authorized payload in a local, network-disabled browser."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu"],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                java_script_enabled=True,
            )
            async def local_only(route: Any) -> None:
                if route.request.url.startswith("file:"):
                    await route.continue_()
                else:
                    await route.abort()

            await context.route("**/*", local_only)
            page = await context.new_page()
            await page.add_init_script(
                "window.__PLAYITOUT_WHATIF_PAYLOAD__ = " + json.dumps(payload) + ";"
            )
            await page.goto(_RESOURCE.as_uri(), wait_until="load", timeout=15_000)
            goal_id = payload["goal"]["goal_id"]
            await page.locator(f'.mcp-what-if[data-goal-id="{goal_id}"]').wait_for(timeout=15_000)
            await page.add_style_tag(content=_EXPORT_STYLE)
            await page.evaluate("document.fonts.ready")
            await page.wait_for_timeout(250)
            image = await page.locator(".mcp-what-if").screenshot(
                animations="disabled", timeout=15_000
            )
            with Image.open(BytesIO(image)) as result:
                output = BytesIO()
                result.save(output, format="PNG", optimize=True)
                return output.getvalue()
        finally:
            await browser.close()
