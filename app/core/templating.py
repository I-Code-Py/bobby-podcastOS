from __future__ import annotations

from markupsafe import Markup
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")


def sparkline(values: list[int | float], width: int = 140, height: int = 30) -> Markup:
    if len(values) < 2:
        flat = values[0] if values else 0
        return Markup(
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<line x1="0" y1="{height//2}" x2="{width}" y2="{height//2}" '
            f'stroke="#94a3b8" stroke-width="1.5"/></svg>'
        )

    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    pad = 2

    def _x(i: int) -> float:
        return pad + (i / (len(values) - 1)) * (width - 2 * pad)

    def _y(v: float) -> float:
        return pad + (1 - (v - mn) / rng) * (height - 2 * pad)

    pts = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(values))
    return Markup(
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{pts}" fill="none" stroke="#6366f1" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def linechart(
    values: list[int | float],
    width: int = 640,
    height: int = 160,
    labels: list[str] | None = None,
) -> Markup:
    if len(values) < 2:
        return Markup(
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<text x="{width//2}" y="{height//2}" text-anchor="middle" '
            f'fill="#94a3b8" font-size="13">Pas encore assez de données</text></svg>'
        )

    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    pad_x, pad_top, pad_bot = 40, 10, 30

    def _x(i: int) -> float:
        return pad_x + (i / (len(values) - 1)) * (width - pad_x - 4)

    def _y(v: float) -> float:
        return pad_top + (1 - (v - mn) / rng) * (height - pad_top - pad_bot)

    pts_line = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(values))
    # Closed polygon for area fill
    pts_area = (
        f"{_x(0):.1f},{height - pad_bot} "
        + pts_line
        + f" {_x(len(values)-1):.1f},{height - pad_bot}"
    )

    # Y-axis grid lines (3 levels)
    grid_lines = ""
    for level in [0, 0.5, 1]:
        y_val = mn + level * rng
        y_pos = _y(y_val)
        label = _fmt_int(y_val)
        grid_lines += (
            f'<line x1="{pad_x}" y1="{y_pos:.1f}" x2="{width-4}" y2="{y_pos:.1f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
            f'<text x="{pad_x-4}" y="{y_pos+4:.1f}" text-anchor="end" '
            f'fill="#94a3b8" font-size="10">{label}</text>'
        )

    # X-axis labels (up to 7)
    x_labels = ""
    if labels:
        step = max(1, len(labels) // 7)
        for i in range(0, len(labels), step):
            x_labels += (
                f'<text x="{_x(i):.1f}" y="{height - 6}" text-anchor="middle" '
                f'fill="#94a3b8" font-size="9">{labels[i]}</text>'
            )

    return Markup(
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="overflow:visible">'
        f'{grid_lines}'
        f'<polygon points="{pts_area}" fill="#6366f1" fill-opacity="0.08"/>'
        f'<polyline points="{pts_line}" fill="none" stroke="#6366f1" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{x_labels}'
        f'</svg>'
    )


def _fmt_int(v: float) -> str:
    v = int(v)
    if v >= 1_000_000:
        return f"{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v//1_000}k"
    return str(v)


# Register as Jinja2 globals
templates.env.globals["sparkline"] = sparkline
templates.env.globals["linechart"] = linechart
templates.env.globals["fmt_int"] = _fmt_int
