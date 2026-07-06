from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader
from markupsafe import Markup

from app.core.auth.csrf import get_csrf_token

CORE_TEMPLATES = Path(__file__).parent / "templates"
CLIPPERS_TEMPLATES = Path(__file__).parent.parent / "modules" / "clippers" / "templates"

FLASH_SESSION_KEY = "flash_messages"


def flash(request: Request, message: str, category: str = "info") -> None:
    messages = request.session.setdefault(FLASH_SESSION_KEY, [])
    messages.append({"message": message, "category": category})
    request.session[FLASH_SESSION_KEY] = messages


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop(FLASH_SESSION_KEY, [])


def format_euros(cents: int | None) -> str:
    if cents is None:
        cents = 0
    euros = cents / 100
    return f"{euros:,.2f} €".replace(",", " ").replace(".", ",")


def format_views(views: int | None) -> str:
    return f"{views or 0:,}".replace(",", " ")


def _svg_polyline(values: list[int], width: int, height: int, pad: int,
                  stroke_width: float, area: bool) -> str:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    points = []
    for i, v in enumerate(values):
        x = pad + (inner_w * i / (n - 1) if n > 1 else inner_w / 2)
        y = height - pad - (v - lo) / span * inner_h
        points.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(points)
    parts = [f'<svg class="chart" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
             f'role="img">']
    if area and n > 1:
        parts.append(
            f'<polygon fill="currentColor" fill-opacity="0.12" stroke="none" '
            f'points="{pad},{height - pad} {poly} {width - pad},{height - pad}"/>'
        )
    parts.append(
        f'<polyline fill="none" stroke="currentColor" stroke-width="{stroke_width}" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{poly}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def sparkline(values, width: int = 140, height: int = 30) -> Markup:
    """Petite courbe SVG inline (sans dépendance) pour une série de vues."""
    values = [int(v) for v in values if v is not None]
    if not values:
        return Markup('<span class="muted">—</span>')
    return Markup(_svg_polyline(values, width, height, pad=2,
                                stroke_width=1.5, area=False))


def linechart(values, width: int = 640, height: int = 160) -> Markup:
    """Courbe SVG plus grande avec zone remplie, pour une évolution."""
    values = [int(v) for v in values if v is not None]
    if not values:
        return Markup('<p class="muted">Pas encore de données — l\'historique se '
                      'construit à chaque scraping quotidien.</p>')
    return Markup(_svg_polyline(values, width, height, pad=6,
                                stroke_width=2, area=True))


templates = Jinja2Templates(directory=str(CORE_TEMPLATES))
templates.env.loader = ChoiceLoader(
    [FileSystemLoader(str(CORE_TEMPLATES)), FileSystemLoader(str(CLIPPERS_TEMPLATES))]
)
templates.env.filters["euros"] = format_euros
templates.env.filters["views"] = format_views
templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["get_flashes"] = pop_flashes
templates.env.globals["sparkline"] = sparkline
templates.env.globals["linechart"] = linechart
