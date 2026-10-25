"""Odds Explorer MCP Apps view contract: handshake strings and host-driven data."""

from personal_markets.remote_mcp.odds_app import ODDS_EXPLORER_HTML, ODDS_UI_MIME, ODDS_UI_URI


def test_odds_explorer_html_speaks_current_mcp_apps_handshake() -> None:
    html = ODDS_EXPLORER_HTML
    assert "method: \"ui/initialize\"" in html or '"ui/initialize"' in html
    assert "appInfo" in html
    assert "clientInfo" not in html
    assert "ui/notifications/initialized" in html
    assert "ui/notifications/tool-result" in html
    assert "ui/notifications/size-changed" in html
    assert "setTimeout(sendInitialized, 500)" in html
    assert "if (hostReady) return;" in html
    assert "pio_at_" not in html
    assert "Bearer" not in html
    assert "1D" in html and "ALL" in html


def test_odds_explorer_uri_and_mime_match_sdk_constants() -> None:
    assert ODDS_UI_URI.startswith("ui://")
    assert ODDS_UI_MIME == "text/html;profile=mcp-app"
