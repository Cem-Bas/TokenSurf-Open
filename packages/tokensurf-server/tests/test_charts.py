"""Tests for web/charts.py — pure functions, no DB."""

from __future__ import annotations

import re

from tokensurf_server.web.charts import distribution_bars, trend_svg

# ── trend_svg ─────────────────────────────────────────────────────────────────


def test_trend_svg_returns_svg_element():
    svg = trend_svg([0.5, 0.8, 0.6])
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")


def test_trend_svg_point_count():
    values = [0.2, 0.5, 0.7, 0.9]
    svg = trend_svg(values)
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None, "polyline points attribute not found in SVG"
    point_pairs = m.group(1).strip().split()
    assert len(point_pairs) == len(values)


def test_trend_svg_empty_returns_no_data_svg():
    svg = trend_svg([])
    assert "<svg" in svg
    assert "no data" in svg
    assert "<polyline" not in svg


def test_trend_svg_single_value_no_division_error():
    # n=1: no division by (n-1), x falls at the midpoint
    svg = trend_svg([0.75])
    assert "<svg" in svg
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None
    assert len(m.group(1).strip().split()) == 1


def test_trend_svg_no_injection_in_points():
    svg = trend_svg([0.0, 0.5, 1.0])
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None
    pts = m.group(1)
    assert "<" not in pts
    assert ">" not in pts
    # Points must contain only digits, dots, commas, and spaces
    assert re.fullmatch(r"[\d., ]+", pts) is not None


def test_trend_svg_clamps_out_of_range_values():
    # Values below 0 or above 1 must not produce bogus coordinates or crash
    svg = trend_svg([-0.5, 0.5, 1.5])
    assert "<svg" in svg
    assert "<polyline" in svg
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None
    assert len(m.group(1).strip().split()) == 3


def test_trend_svg_default_dimensions():
    svg = trend_svg([0.5])
    assert 'width="520"' in svg
    assert 'height="120"' in svg


def test_trend_svg_custom_dimensions():
    svg = trend_svg([0.5], width=300, height=60)
    assert 'width="300"' in svg
    assert 'height="60"' in svg


def test_trend_svg_baseline_line_present():
    svg = trend_svg([0.5, 0.8])
    assert "<line" in svg


def test_trend_svg_two_points_horizontal_positions_differ():
    """With two values the x-coordinates of the two points must differ."""
    svg = trend_svg([0.3, 0.7])
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None
    pairs = m.group(1).strip().split()
    assert len(pairs) == 2
    x0 = float(pairs[0].split(",")[0])
    x1 = float(pairs[1].split(",")[0])
    assert x1 > x0


def test_trend_svg_high_value_maps_to_lower_y():
    """pass_rate=1.0 (top) must produce a smaller y-coordinate than pass_rate=0.0 (bottom)."""
    svg = trend_svg([1.0, 0.0])
    m = re.search(r'points="([^"]+)"', svg)
    assert m is not None
    pairs = m.group(1).strip().split()
    y_high = float(pairs[0].split(",")[1])
    y_low = float(pairs[1].split(",")[1])
    assert y_high < y_low


# ── distribution_bars ─────────────────────────────────────────────────────────


def test_distribution_bars_four_bar_classes():
    html = distribution_bars([1, 2, 3, 4])
    assert "bar-poor" in html
    assert "bar-fair" in html
    assert "bar-good" in html
    assert "bar-excellent" in html


def test_distribution_bars_heights_reflect_counts():
    # total=100; percentages are exact integers
    html = distribution_bars([10, 20, 30, 40])
    assert "height:10%" in html
    assert "height:20%" in html
    assert "height:30%" in html
    assert "height:40%" in html


def test_distribution_bars_all_zero_gives_min_height():
    html = distribution_bars([0, 0, 0, 0])
    # Every bar must carry min-height so they are visible
    assert html.count("min-height") == 4


def test_distribution_bars_labels_present():
    html = distribution_bars([1, 1, 1, 1])
    for label in ("poor", "fair", "good", "excellent"):
        assert label in html


def test_distribution_bars_no_script_injection():
    html = distribution_bars([10, 0, 80, 10])
    assert "<script" not in html
    assert "onerror" not in html


def test_distribution_bars_single_nonempty_bucket():
    # All scores in the 'excellent' bucket
    html = distribution_bars([0, 0, 0, 100])
    assert "height:0%" in html  # poor, fair, good are zero
    assert "height:100%" in html  # excellent


def test_distribution_bars_returns_html_string():
    html = distribution_bars([25, 25, 25, 25])
    assert isinstance(html, str)
    assert html.startswith("<div")
