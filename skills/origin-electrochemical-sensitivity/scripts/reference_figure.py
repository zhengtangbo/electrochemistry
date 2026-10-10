"""Render a publication-style calibration figure from a verified Origin fit.

The layout follows the user's example: white canvas, boxed black axes, black
square observations, a thin red fit line, and K/R² inside the lower-right plot.
The numerical fit is supplied by Origin; this module does no new regression.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import pandas as pd


def nice_step(raw: float) -> float:
    exponent = math.floor(math.log10(raw))
    magnitude = 10 ** exponent
    for base in (1, 2, 2.5, 5, 10):
        if base * magnitude >= raw:
            return base * magnitude
    return 10 * magnitude


def axis_range(values: list[float]) -> tuple[float, float, float]:
    low, high = min(values), max(values)
    span = high - low
    if span <= 0:
        span = max(abs(low) * 0.2, 1.0)
    step = nice_step(span / 4)
    low = math.floor((low - 0.08 * span) / step) * step
    high = math.ceil((high + 0.08 * span) / step) * step
    if high <= low:
        high = low + step
    return low, high, step


def tick_text(value: float) -> str:
    return f"{value:.8g}"


def find_chrome() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return Path(found)
    raise RuntimeError("No Chrome or Edge executable found to render the reference-style PNG")


def render_reference_figure(report: dict, calibration: pd.DataFrame, run_dir: Path) -> list[str]:
    if report.get("status") != "success":
        raise ValueError("Reference-style figure requires a verified Origin fit")
    low_fit, high_fit = report["fit_range"]
    frame = calibration[(calibration["concentration"] >= low_fit) &
                        (calibration["concentration"] <= high_fit)]
    if len(frame) < 3:
        raise ValueError("Reference-style figure needs at least three fitted concentration levels")
    xs = frame["concentration"].to_numpy(dtype=float)
    ys = frame["mean_delta"].to_numpy(dtype=float)
    slope, intercept = float(report["K"]), float(report["intercept"])
    ymin, ymax, ystep = axis_range([*ys, *(slope * xs + intercept)])
    xmin, xmax, xstep = axis_range(list(xs))

    # Match the supplied 3216 × 2461 image's canvas and plot-frame proportions.
    width, height = 1800, 1377
    left, top, pw, ph = 322, 159, 1226, 988
    px = lambda x: left + (x - xmin) / (xmax - xmin) * pw
    py = lambda y: top + ph - (y - ymin) / (ymax - ymin) * ph
    conc_unit = str(report["concentration_unit"])
    current_unit = str(report["current_unit"])
    is_density = "/cm" in current_unit or "cm⁻²" in current_unit
    display_current_unit = current_unit.replace("/cm²", " cm⁻²").replace("/cm^2", " cm⁻²")
    y_label = f"Δcurrent density ({display_current_unit})" if is_density else f"Δcurrent ({current_unit})"
    slope_unit = (current_unit.replace("/cm²", "·cm⁻²").replace("/cm^2", "·cm⁻²") +
                  "·" + conc_unit + "⁻¹")
    k_text = f"K={slope:.6g}{slope_unit}"
    r2_text = f"R² = {report['r_squared']:.5f}" if report.get("r_squared") is not None else "R² = undefined"
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<rect x="{left}" y="{top}" width="{pw}" height="{ph}" fill="none" stroke="#000000" stroke-width="3.5"/>',
    ]
    # Draw labels/ticks without grid lines, as in the reference image.
    nx = int(round((xmax - xmin) / xstep))
    for i in range(nx + 1):
        val = xmin + i * xstep
        xp = px(val)
        pieces.append(f'<line x1="{xp:.2f}" y1="{top+ph}" x2="{xp:.2f}" y2="{top+ph+17}" stroke="#000" stroke-width="3"/>')
        pieces.append(f'<text x="{xp:.2f}" y="{top+ph+70}" text-anchor="middle" font-family="Arial" font-size="43">{html.escape(tick_text(val))}</text>')
    ny = int(round((ymax - ymin) / ystep))
    for i in range(ny + 1):
        val = ymin + i * ystep
        yp = py(val)
        pieces.append(f'<line x1="{left-17}" y1="{yp:.2f}" x2="{left}" y2="{yp:.2f}" stroke="#000" stroke-width="3"/>')
        pieces.append(f'<text x="{left-31}" y="{yp+14:.2f}" text-anchor="end" font-family="Arial" font-size="43">{html.escape(tick_text(val))}</text>')
    pieces.append(f'<text x="{left+pw/2}" y="{height-65}" text-anchor="middle" font-family="Arial" font-size="48">Concentration ({html.escape(conc_unit)})</text>')
    pieces.append(f'<text x="190" y="{top+ph/2}" transform="rotate(-90 190 {top+ph/2})" text-anchor="middle" font-family="Arial" font-size="48">{html.escape(y_label)}</text>')
    pieces.append(f'<line x1="{px(float(xs.min())):.2f}" y1="{py(slope*float(xs.min())+intercept):.2f}" x2="{px(float(xs.max())):.2f}" y2="{py(slope*float(xs.max())+intercept):.2f}" stroke="#f00000" stroke-width="2.4"/>')
    for x, y in zip(xs, ys):
        pieces.append(f'<rect x="{px(float(x))-10:.2f}" y="{py(float(y))-10:.2f}" width="20" height="20" fill="#000000"/>')
    pieces.append(f'<text x="{left+0.55*pw:.2f}" y="{top+0.71*ph:.2f}" font-family="Arial" font-size="42">{html.escape(k_text)}</text>')
    pieces.append(f'<text x="{left+0.55*pw:.2f}" y="{top+0.77*ph:.2f}" font-family="Arial" font-size="42">{html.escape(r2_text)}</text>')
    pieces.append('</svg>')
    svg = run_dir / "sensitivity_reference_style.svg"
    png = run_dir / "sensitivity_reference_style.png"
    svg.write_text("\n".join(pieces), encoding="utf-8")

    browser = find_chrome()
    with tempfile.TemporaryDirectory(prefix="origin_sensitivity_render_", ignore_cleanup_errors=True) as profile:
        cmd = [str(browser), "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
               f"--user-data-dir={profile}", f"--window-size={width},{height}",
               f"--screenshot={png}", svg.as_uri()]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 15
        while (not png.is_file() or png.stat().st_size == 0) and time.monotonic() < deadline:
            time.sleep(0.2)
        if not png.is_file() or png.stat().st_size == 0:
            raise RuntimeError(f"Reference-style PNG render failed (exit {result.returncode}): {result.stderr[-1000:]}")
    return [str(svg), str(png)]
