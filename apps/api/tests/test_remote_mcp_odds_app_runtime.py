"""Exercise the embedded MCP Apps chart script in a DOM, including host messages."""

import subprocess

from personal_markets.remote_mcp.odds_app import ODDS_EXPLORER_HTML


def test_chart_ignores_unrelated_and_late_tool_results() -> None:
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(0, 'utf8'), {
  runScripts: 'dangerously', url: 'https://example.invalid/'
});
const { window } = dom;
const doc = window.document;
function notify(method, params) {
  window.dispatchEvent(new window.MessageEvent('message', {
    data: { jsonrpc: '2.0', method, params }
  }));
}
function chart(goal, count, value = 76.46) {
  return {
    goal_id: goal, status: 'PUBLISHED', points: Array.from({length: count}, (_, i) => ({
      timestamp_ms: Date.UTC(2026, 9, 1 + i), probability_pct: value,
      receipt_id: `${goal}-${i}`
    }))
  };
}
const price = () => doc.getElementById('price').textContent;
const points = () => window.PlayItOutOdds.visiblePoints();
const eighteen = chart('fde', 18);
window.dispatchEvent(new window.MessageEvent('message', { data: {
  jsonrpc: '2.0', id: 'initialize-1', result: {
    protocolVersion: '2026-01-26', hostContext: {
      toolResult: { structuredContent: eighteen }
    }
  }
}}));
assert.equal(points().length, 18);
assert.equal(price(), '76.5%');
notify('ui/notifications/tool-result', { structuredContent: eighteen });
notify('ui/notifications/tool-result', { structuredContent: chart('fde', 1) });
assert.equal(points().length, 18);
notify('ui/notifications/tool-result', { structuredContent: {
  goal_id: 'fde', status: 'NEEDS_INPUT', probability: null
}});
notify('ui/notifications/tool-result', { status: 'EXPLORATORY' });
notify('ui/notifications/tool-result', {});
assert.equal(points().length, 18);
assert.equal(price(), '76.5%');
notify('ui/notifications/tool-result', { structuredContent: chart('other', 1, 22) });
assert.equal(points().length, 18);
notify('ui/notifications/tool-input', { arguments: { goal_id: 'other' } });
assert.equal(price(), '—');
notify('ui/notifications/tool-result', { structuredContent: eighteen });
assert.equal(points().length, 0);
notify('ui/notifications/tool-result', { structuredContent: chart('other', 2, 22) });
assert.equal(points().length, 2);
assert.equal(price(), '22.0%');
notify('ui/notifications/tool-result', { structuredContent: chart('other', 3, 24) });
assert.equal(points().length, 3);
assert.equal(price(), '24.0%');
notify('ui/notifications/tool-result', { structuredContent: eighteen });
assert.equal(points().length, 3);
window.PlayItOutOdds.ingest({ structuredContent: {
  ...chart('other', 4, 22), points: [
    chart('other', 4, 22).points[3],
    {timestamp_ms: NaN, probability_pct: 50, receipt_id: 'bad'},
    chart('other', 4, 22).points[0],
    chart('other', 4, 22).points[1],
    chart('other', 4, 22).points[2],
    chart('other', 4, 22).points[3]
  ]
}});
assert.equal(points().length, 4);
assert.ok(points()[0].timestamp_ms < points()[1].timestamp_ms);
for (const range of ['1D', '1W', '1M', '1Y', 'ALL']) {
  doc.querySelector(`[data-range="${range}"]`).click();
  assert.ok(points().length >= 1);
}
window.close();
"""
    result = subprocess.run(
        ["node", "-e", script],
        input=ODDS_EXPLORER_HTML,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
