"""Owner-bound chart series and a static PNG fallback.

Series are real published receipts. A single receipt in a 1D window stays a
single point; nothing is interpolated into extra observations.
"""

from __future__ import annotations

import struct
import zlib
from datetime import datetime, timedelta
from typing import Any, Literal

from personal_markets.forecasting.repository import PublishedBaseline
from personal_markets.remote_mcp.temporal import publication_time, sort_history

RangeKey = Literal["1D", "1W", "1M", "1Y", "ALL"]
RANGE_DELTAS: dict[RangeKey, timedelta | None] = {
    "1D": timedelta(days=1),
    "1W": timedelta(days=7),
    "1M": timedelta(days=30),
    "1Y": timedelta(days=365),
    "ALL": None,
}

BG = (248, 248, 245)
INK = (32, 33, 31)
MUTED = (119, 123, 120)
ACCENT = (41, 159, 150)
GRID = (227, 228, 223)

_FONT: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("01110", "10001", "00001", "00110", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("01110", "10000", "11110", "10001", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "%": ("11001", "11010", "00100", "01000", "10110", "10011", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    "a": ("00000", "01110", "00001", "01111", "10001", "10001", "01111"),
    "c": ("00000", "01110", "10001", "10000", "10000", "10001", "01110"),
    "d": ("00001", "00001", "01111", "10001", "10001", "10001", "01111"),
    "e": ("00000", "01110", "10001", "11111", "10000", "10001", "01110"),
    "f": ("00110", "01001", "01000", "11100", "01000", "01000", "01000"),
    "g": ("00000", "01111", "10001", "10001", "01111", "00001", "01110"),
    "h": ("10000", "10000", "11110", "10001", "10001", "10001", "10001"),
    "i": ("00100", "00000", "01100", "00100", "00100", "00100", "01110"),
    "l": ("01100", "00100", "00100", "00100", "00100", "00100", "01110"),
    "n": ("00000", "00000", "11110", "10001", "10001", "10001", "10001"),
    "o": ("00000", "00000", "01110", "10001", "10001", "10001", "01110"),
    "p": ("00000", "11110", "10001", "10001", "11110", "10000", "10000"),
    "r": ("00000", "00000", "10110", "11001", "10000", "10000", "10000"),
    "s": ("00000", "01110", "10000", "01110", "00001", "10001", "01110"),
    "t": ("00100", "00100", "11111", "00100", "00100", "00100", "00010"),
    "u": ("00000", "00000", "10001", "10001", "10001", "10001", "01111"),
    "v": ("00000", "00000", "10001", "10001", "10001", "01010", "00100"),
}


def series_from_history(history: list[PublishedBaseline]) -> list[dict[str, Any]]:
    points = []
    for item in sort_history(history):
        published = publication_time(item)
        if published is None:
            continue
        if item.source_kind == "synthetic_demo":
            continue
        points.append(
            {
                "timestamp_ms": int(published.timestamp() * 1000),
                "published_at": published.isoformat(),
                "probability": item.probability,
                "probability_pct": item.probability * 100.0,
                "forecast_status": item.forecast_status,
                "receipt_id": item.material_hash,
                "evidence_watermark": item.evidence_watermark,
            }
        )
    return points


def filter_range(
    points: list[dict[str, Any]], range_key: RangeKey, now: datetime | None = None
) -> list[dict[str, Any]]:
    if not points or range_key == "ALL":
        return list(points)
    latest_ms = max(int(item["timestamp_ms"]) for item in points)
    delta = RANGE_DELTAS[range_key]
    if delta is None:
        return list(points)
    cutoff = latest_ms - int(delta.total_seconds() * 1000)
    filtered = [item for item in points if int(item["timestamp_ms"]) >= cutoff]
    return filtered if filtered else [points[-1]]


def _set(
    pixels: list[list[tuple[int, int, int]]], x: int, y: int, color: tuple[int, int, int]
) -> None:
    if 0 <= y < len(pixels) and 0 <= x < len(pixels[0]):
        pixels[y][x] = color


def _line(
    pixels: list[list[tuple[int, int, int]]],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    x, y = x0, y0
    while True:
        _set(pixels, x, y, color)
        if x == x1 and y == y1:
            return
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x += sx
        if doubled <= dx:
            error += dx
            y += sy


def _text(
    pixels: list[list[tuple[int, int, int]]],
    x: int,
    y: int,
    value: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    cursor = x
    for char in value:
        glyph = _FONT.get(char, _FONT[" "])
        for row, pattern in enumerate(glyph):
            for col, bit in enumerate(pattern):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        _set(pixels, cursor + col * scale + dx, y + row * scale + dy, color)
        cursor += 6 * scale


def _png(pixels: list[list[tuple[int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for red, green, blue in row:
            raw.extend((red, green, blue))
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
    )


def render_odds_png(
    points: list[dict[str, Any]],
    *,
    title: str,
    width: int = 800,
    height: int = 360,
    now: datetime | None = None,
) -> bytes:
    del now
    pixels = [[BG for _ in range(width)] for _ in range(height)]
    left, right, top, bottom = 48, width - 24, 56, height - 36
    for x in range(width):
        for y in range(40):
            _set(pixels, x, y, BG)
    _text(pixels, 16, 12, _header_text(points, title), INK, scale=2)
    if not points:
        _text(pixels, 16, height // 2, "no published forecast", MUTED, scale=2)
        return _png(pixels)

    values = [float(item["probability_pct"]) for item in points]
    times = [int(item["timestamp_ms"]) for item in points]
    lo, hi = min(values), max(values)
    span = max(hi - lo, 1.0)
    t0, t1 = min(times), max(times)
    tspan = max(t1 - t0, 1)

    for index in range(5):
        y = top + int((bottom - top) * index / 4)
        _line(pixels, left, y, right, y, GRID)

    coords: list[tuple[int, int]] = []
    for time_ms, value in zip(times, values, strict=True):
        x = left + int((right - left) * (time_ms - t0) / tspan)
        y = bottom - int((bottom - top) * (value - lo) / span)
        coords.append((x, y))

    if len(coords) == 1:
        x, y = coords[0]
        for radius in range(5):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= radius * radius:
                        color = ACCENT if radius <= 3 else BG
                        _set(pixels, x + dx, y + dy, color if radius <= 3 else ACCENT)
                        if radius == 4:
                            _set(pixels, x + dx, y + dy, ACCENT)
        _text(pixels, x + 8, y - 18, f"{values[0]:.1f}%", INK, scale=2)
    else:
        for (x0, y0), (x1, y1) in zip(coords, coords[1:], strict=False):
            _line(pixels, x0, y0, x1, y1, ACCENT)
            _line(pixels, x0, y0 + 1, x1, y1 + 1, ACCENT)
        x, y = coords[-1]
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy <= 9:
                    _set(pixels, x + dx, y + dy, ACCENT)

    _text(pixels, 16, height - 24, "static png  not interactive", MUTED, scale=1)
    return _png(pixels)


def _header_text(points: list[dict[str, Any]], title: str) -> str:
    del title
    if not points:
        return "odds  not priced"
    latest = float(points[-1]["probability_pct"])
    return f"odds  {latest:.1f}%"


def is_png(payload: bytes) -> bool:
    return payload.startswith(b"\x89PNG\r\n\x1a\n")
