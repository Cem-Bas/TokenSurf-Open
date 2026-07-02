"""Server-rendered chart helpers — pure functions, zero external dependencies.

Both functions return strings safe to embed in Jinja2 templates with ``| safe``.
trend_svg emits numbers only into SVG attributes (no user data touches the markup).
distribution_bars uses hardcoded bucket labels; count values are formatted as
integers, never interpolated as raw strings.
"""

from __future__ import annotations


def trend_svg(
    values: list[float],
    *,
    width: int = 520,
    height: int = 120,
) -> str:
    """Return an inline ``<svg>`` polyline of pass-rates mapped to *height*.

    *values* is a list of floats in [0, 1] ordered oldest-to-newest.
    Values outside [0, 1] are clamped. Empty *values* → a "no data" placeholder
    svg of the same dimensions. The returned string is safe to embed with ``| safe``
    because only numeric literals appear in the SVG attributes.
    """
    if not values:
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="no data">'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'fill="#6a7080" font-size="13">no data</text></svg>'
        )
    pad = 8
    n = len(values)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    points_list: list[str] = []
    for i, raw in enumerate(values):
        v = 0.0 if raw < 0 else 1.0 if raw > 1 else float(raw)
        x = pad + (inner_w / 2 if n == 1 else inner_w * i / (n - 1))
        y = pad + inner_h * (1.0 - v)
        points_list.append(f"{x:.1f},{y:.1f}")
    points = " ".join(points_list)
    baseline_y = pad + inner_h
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="pass-rate trend">'
        f'<line x1="{pad}" y1="{baseline_y:.1f}" x2="{width - pad}" y2="{baseline_y:.1f}" '
        f'stroke="#e5e0d6" stroke-width="1"/>'
        f'<polyline fill="none" stroke="#4f6df5" stroke-width="2" points="{points}"/>'
        "</svg>"
    )


def distribution_bars(distribution: list[int]) -> str:
    """Return four CSS-flex bars for the score buckets [poor, fair, good, excellent].

    Bar heights are the integer percentage of the total count. When the total is
    zero, every bar gets a min-height so the (empty) chart is still visible. Labels
    are hardcoded; counts are formatted as integers — no user data reaches the markup.
    """
    labels = ["poor", "fair", "good", "excellent"]
    counts = [int(c) for c in ([*list(distribution), 0, 0, 0, 0][:4])]
    total = sum(counts)
    bars: list[str] = []
    for label, count in zip(labels, counts, strict=False):
        pct = int(round(100 * count / total)) if total else 0
        style = f"height:{pct}%;min-height:3px" if total == 0 else f"height:{pct}%"
        bars.append(
            f'<div class="dist-col">'
            f'<div class="dist-bar bar-{label}" style="{style}"></div>'
            f'<div class="dist-label">{label}</div>'
            f"</div>"
        )
    return f'<div class="dist-bars">{"".join(bars)}</div>'
