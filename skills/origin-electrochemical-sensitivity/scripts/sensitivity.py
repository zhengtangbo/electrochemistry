"""Traceable peak-to-baseline sensitivity analysis with a native OriginPro fit."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import uuid

import numpy as np
import pandas as pd

from reference_figure import axis_range, render_reference_figure


DEFAULT_PEAK_QUALITY = {
    "min_prominence_snr": 5.0,
    "min_prominence_fraction": 0.25,
    "max_shift_v": 0.03,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def publish_delivery_copies(report: dict, qa: dict, root: Path) -> list[dict]:
    """Publish verified native exports alongside the external presentation PNG."""
    require(qa.get("status") == "success" and qa.get("checks", {}).get("opju_reopened"),
            "A verified, reopened Origin project is required for native delivery copies")
    roles = {".png": ("Origin原生导出图_标定.png", "Native Origin PNG export"),
             ".pdf": ("Origin原生导出图_标定.pdf", "Native Origin PDF export"),
             ".opju": ("Origin可编辑工程_标定.opju", "Editable native Origin project")}
    copies = []
    for suffix, (name, method) in roles.items():
        items = [item for item in qa["files"] if Path(item["path"]).suffix.lower() == suffix]
        require(len(items) == 1, f"Expected one verified native Origin {suffix} file")
        item = items[0]
        source = Path(item["path"])
        require(source.is_file() and source.stat().st_size > 0,
                f"Missing verified native file: {source}")
        require(digest(source) == item["sha256"], f"Native file differs from its QA record: {source}")
        target = root / name
        shutil.copy2(source, target)
        require(digest(target) == item["sha256"], "Native delivery copy differs")
        copies.append({"path": str(target), "method": method, "sha256": item["sha256"]})
    presentation = [Path(p) for p in report["reference_style_files"] if Path(p).suffix.lower() == ".png"]
    require(len(presentation) == 1, "Expected one reference-style presentation PNG")
    source = presentation[0]
    require(source.is_file() and source.stat().st_size > 0, "Reference-style PNG is missing")
    target = root / "标准标定图.png"
    shutil.copy2(source, target)
    require(digest(source) == digest(target), "Presentation delivery copy differs")
    copies.append({"path": str(target), "method": "Script-drawn SVG rendered to PNG", "sha256": digest(target)})
    (root / "00_绘图版本说明.txt").write_text(
        "标准标定图.png：由脚本按实际提取值和已验证的 Origin 拟合系数绘制 SVG 后渲染。\n"
        "Origin原生导出图_标定.png / .pdf：由真实 Origin 图形对象直接导出，非外部渲染图。\n"
        "Origin可编辑工程_标定.opju：原生工程，已经保存后重新打开核验。\n"
        "两种图使用同一标定输入和同一拟合定义；没有调用生成式 AI 生图。\n"
        "拟合线的绘图采样点是公式预测值，不是新增实测点。\n",
        encoding="utf-8")
    return copies


def number(value: object, label: str) -> float:
    require(not isinstance(value, bool), f"{label} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    require(math.isfinite(result), f"{label} must be finite")
    return result


def interval(value: object, label: str) -> tuple[float, float]:
    require(isinstance(value, list) and len(value) == 2, f"{label} must be [low, high]")
    low, high = (number(v, label) for v in value)
    require(low < high, f"{label} must be increasing")
    return low, high


def plain_unit(value: object, label: str) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 25, f"{label} must be a short string")
    require(not any(c in value for c in '\r\n;"'), f"{label} contains unsupported label characters")
    return value


def plot_unit(value: str) -> str:
    return value.replace("μ", "u").replace("µ", "u").replace("²", "^2")


def validate_manifest(manifest: dict) -> dict:
    require(isinstance(manifest, dict), "Manifest must be a JSON object")
    for key in ("analyte", "concentration_unit", "current_unit", "potential_unit"):
        require(key in manifest, f"Missing {key}")
    require(isinstance(manifest["analyte"], str) and manifest["analyte"].strip(), "analyte is required")
    for key in ("concentration_unit", "current_unit", "potential_unit"):
        plain_unit(manifest[key], key)
    if "source_current_unit" in manifest:
        plain_unit(manifest["source_current_unit"], "source_current_unit")
    scale = number(manifest.get("current_scale", 1), "current_scale")
    require(scale > 0, "current_scale must be positive")
    manifest["current_scale"] = scale
    cols = manifest.get("columns")
    require(isinstance(cols, dict) and all(isinstance(cols.get(k), str) and cols[k] for k in ("x", "y")),
            "columns.x and columns.y are required")
    require(cols["x"] != cols["y"], "Potential and current columns must differ")
    peak = manifest.get("peak")
    require(isinstance(peak, dict) and peak.get("direction") in ("up", "down"),
            "peak.direction must be up or down")
    peak_window = interval(peak.get("window"), "peak.window")
    quality = peak.get("quality", {})
    require(isinstance(quality, dict), "peak.quality must be an object")
    require(set(quality) <= set(DEFAULT_PEAK_QUALITY), "Unsupported peak.quality setting")
    validated_quality = {}
    for key, default in DEFAULT_PEAK_QUALITY.items():
        value = number(quality.get(key, default), f"peak.quality.{key}")
        require(value > 0, f"peak.quality.{key} must be positive")
        if key == "min_prominence_fraction":
            require(value <= 1, "min_prominence_fraction must be at most 1")
        validated_quality[key] = value
    peak["quality"] = validated_quality
    baseline = manifest.get("baseline")
    require(isinstance(baseline, dict) and baseline.get("mode") in ("constant", "linear"),
            "baseline.mode must be constant or linear")
    windows = baseline.get("windows")
    count = 1 if baseline["mode"] == "constant" else 2
    require(isinstance(windows, list) and len(windows) == count,
            f"baseline.windows must contain {count} window(s)")
    windows = [interval(w, f"baseline.windows[{i}]") for i, w in enumerate(windows)]
    if count == 1:
        require(windows[0][1] < peak_window[0] or windows[0][0] > peak_window[1],
                "Constant baseline window must be outside the peak window")
    else:
        require(windows[0][1] < peak_window[0] and windows[1][0] > peak_window[1],
                "Linear baseline windows must flank the peak window in increasing potential order")
    samples = manifest.get("samples")
    require(isinstance(samples, list) and len(samples) >= 3, "At least three samples are required")
    for i, sample in enumerate(samples):
        require(isinstance(sample, dict) and isinstance(sample.get("path"), str) and sample["path"],
                f"samples[{i}].path is required")
        require(number(sample.get("concentration"), f"samples[{i}].concentration") >= 0,
                f"samples[{i}].concentration must be nonnegative")
    require(len({number(s["concentration"], "concentration") for s in samples}) >= 3,
            "At least three distinct concentrations are required")
    if "fit_range" in manifest:
        interval(manifest["fit_range"], "fit_range")
    if "electrode_area_cm2" in manifest:
        require(number(manifest["electrode_area_cm2"], "electrode_area_cm2") > 0,
                "electrode_area_cm2 must be positive")
    return manifest


def read_curve(sample: dict, root: Path, default_columns: dict) -> tuple[Path, np.ndarray, np.ndarray, dict]:
    path = Path(sample["path"])
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    require(path.is_file(), f"Source not found: {path}")
    suffix = path.suffix.lower()
    x_name = sample.get("x_column", default_columns["x"])
    y_name = sample.get("y_column", default_columns["y"])
    if suffix in (".xlsx", ".xlsm"):
        frame = pd.read_excel(path, sheet_name=sample.get("sheet", 0),
                              skiprows=sample.get("skiprows", 0), engine="openpyxl")
    elif suffix in (".csv", ".tsv", ".txt", ".dat"):
        default_sep = "," if suffix == ".csv" else "\t" if suffix == ".tsv" else r"\s+"
        frame = pd.read_csv(path, sep=sample.get("separator", default_sep),
                            skiprows=sample.get("skiprows", 0),
                            encoding=sample.get("encoding", "utf-8-sig"))
    else:
        raise ValueError(f"Unsupported source format: {path.suffix}")
    require(isinstance(frame, pd.DataFrame), f"Expected one worksheet from {path}")
    require(x_name in frame and y_name in frame, f"Missing {x_name!r} or {y_name!r} in {path}")
    row_slice = sample.get("row_slice", [0, len(frame)])
    require(isinstance(row_slice, list) and len(row_slice) == 2 and
            all(isinstance(v, int) and not isinstance(v, bool) for v in row_slice) and
            0 <= row_slice[0] < row_slice[1] <= len(frame),
            f"Invalid row_slice for {path}; use zero-based [start, stop)")
    selected = frame.iloc[row_slice[0]:row_slice[1]]
    require(len(selected) >= 7, f"Too few rows in selected scan branch: {path}")
    x = pd.to_numeric(selected[x_name], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(selected[y_name], errors="coerce").to_numpy(dtype=float)
    require(np.isfinite(x).all() and np.isfinite(y).all(),
            f"Missing/non-numeric current or potential in {path}; inspect the source")
    diff = np.diff(x)
    require((diff >= 0).all() or (diff <= 0).all(),
            f"Potential reverses direction in {path}; select one CV branch with row_slice")
    require(np.ptp(x) > 0, f"Potential does not vary in {path}")
    return path, x, y, {"row_slice": row_slice, "source_sha256": digest(path)}


def extract(x: np.ndarray, y: np.ndarray, manifest: dict, label: str) -> tuple[dict, np.ndarray, np.ndarray]:
    peak_low, peak_high = interval(manifest["peak"]["window"], "peak.window")
    peak_indices = np.flatnonzero((x >= peak_low) & (x <= peak_high))
    require(len(peak_indices) >= 3, f"{label}: fewer than three points in peak window")
    windows = [interval(v, "baseline window") for v in manifest["baseline"]["windows"]]
    anchors = [np.flatnonzero((x >= low) & (x <= high)) for low, high in windows]
    require(all(len(a) >= 2 for a in anchors), f"{label}: baseline window has fewer than two points")
    if manifest["baseline"]["mode"] == "constant":
        baseline = np.full_like(y, float(y[anchors[0]].mean()))
    else:
        x0, x1 = (float(x[a].mean()) for a in anchors)
        y0, y1 = (float(y[a].mean()) for a in anchors)
        require(abs(x1 - x0) > 1e-12, f"{label}: baseline anchors have indistinguishable potential")
        slope = (y1 - y0) / (x1 - x0)
        baseline = y0 + slope * (x - x0)
    sign = 1 if manifest["peak"]["direction"] == "up" else -1
    response = sign * (y - baseline)
    local = int(np.argmax(response[peak_indices]))
    index = int(peak_indices[local])
    anchor_indices = np.concatenate(anchors)
    noise = float(np.sqrt(np.mean((y[anchor_indices] - baseline[anchor_indices]) ** 2)))
    # A visible peak must rise above both shoulders, not just one high point
    # in a sloping trace or the edge of a step.
    shoulder_count = max(1, round(0.2 * len(peak_indices)))
    left = float(np.median(response[peak_indices[:shoulder_count]]))
    right = float(np.median(response[peak_indices[-shoulder_count:]]))
    prominence = float(response[index] - max(left, right))
    snr = prominence / max(noise, 1e-15)
    fraction = prominence / response[index] if response[index] > 0 else 0.0
    quality = {**DEFAULT_PEAK_QUALITY, **manifest["peak"].get("quality", {})}
    issues = []
    if not 0 < local < len(peak_indices) - 1:
        issues.append("candidate is on the search-window boundary")
    if response[index] <= 0:
        issues.append("candidate does not rise above the baseline")
    if prominence <= 0 or snr < quality["min_prominence_snr"]:
        issues.append(f"prominence SNR {snr:.3g} below {quality['min_prominence_snr']:g}")
    if fraction < quality["min_prominence_fraction"]:
        issues.append(f"prominence fraction {fraction:.3g} below {quality['min_prominence_fraction']:g}")
    row = {
        "peak_potential": float(x[index]),
        "peak_current": float(y[index]),
        "baseline_at_peak": float(baseline[index]),
        "signed_delta": float(y[index] - baseline[index]),
        "delta_current": float(response[index]),
        "baseline_anchor_rms": noise,
        "peak_prominence": prominence,
        "peak_prominence_snr": snr,
        "peak_prominence_fraction": fraction,
        "peak_quality": "pass" if not issues else "reject",
        "peak_quality_issues": "; ".join(issues),
        "peak_points": len(peak_indices),
        "baseline_points": len(anchor_indices),
    }
    return row, baseline, response


def make_spec(manifest: dict, run_dir: Path, curve_paths: list[Path], calibration: pd.DataFrame,
              fit: pd.DataFrame, outside: pd.DataFrame) -> dict:
    # The verified Origin 2021 core runner builds one graph layer per project.
    # Keep raw/processed traces as audited CSVs and the native regression in its own OPJU.
    fit_path = run_dir / "fit_points.csv"
    fit.to_csv(fit_path, index=False)
    data: list[dict] = [{"id": "fitpoints", "source": str(fit_path), "object": "worksheet", "missing": "error",
                         "units": {"concentration": plot_unit(manifest["concentration_unit"]),
                                   "mean_delta": plot_unit(manifest["current_unit"])}}]
    fit_plot = {"id": "calibration", "layer": "main", "data": "fitpoints",
                "type": "scatter", "x": "concentration", "y": "mean_delta", "color": "#000000"}
    plots: list[dict] = [fit_plot]
    if len(outside):
        outside_path = run_dir / "outside_fit_range.csv"
        outside.to_csv(outside_path, index=False)
        data.append({"id": "outside", "source": str(outside_path), "object": "worksheet", "missing": "error"})
        plots.append({"id": "outside", "layer": "main", "data": "outside",
                      "type": "scatter", "x": "concentration", "y": "mean_delta", "color": "#999999"})
    xmin, xmax, _ = axis_range(fit["concentration"].to_list())
    ymin, ymax, _ = axis_range(calibration["mean_delta"].to_list())
    concentration_unit = manifest["concentration_unit"]
    current_unit = manifest["current_unit"]
    is_density = "/cm" in current_unit or "cm⁻²" in current_unit
    # Origin 2021 PDF export renders its rich-text superscript escape more
    # reliably than Unicode superscript minus and digits.
    display_unit = current_unit.replace("/cm²", r" cm\+(-2)").replace("/cm^2", r" cm\+(-2)")
    y_title = (f"Δcurrent density ({display_unit})" if is_density
               else f"Δcurrent ({current_unit})")
    slope_unit = (current_unit.replace("/cm²", r"·cm\+(-2)").replace("/cm^2", r"·cm\+(-2)")
                  + "·" + concentration_unit + r"\+(-1)")
    return {
        "schema_version": 1, "id": "electrochemical_sensitivity", "mode": "execute", "executor": "core",
        "runtime": {"show_origin": False, "show_seconds": 0},
        "data": data, "page": {},
        "layers": [{"id": "main", "index": 0}],
        "plots": plots,
        "axes": {
            "main": {"x": {"title": f"Concentration ({concentration_unit})", "limits": [xmin, xmax]},
                     "y": {"title": y_title, "limits": [ymin, ymax]}},
        },
        "annotations": [],
        "style": {"font": "Arial", "font_size": 18, "line_width": 1.0, "symbol_size": 8,
                  "fit_line_color": "#F00000", "hide_legend": True,
                  "reference_calibration": True, "slope_unit": slope_unit},
        "analysis": [{"type": "linear", "plot": "calibration", "annotate": True}],
        "export": {"formats": ["png", "pdf"], "width_px": 2000, "publication": True},
        "notes": "The calibration is fitted by Origin fitLR. Source traces, baseline and peak extraction are auditable in measurements.csv and curve_*.csv.",
    }


def run_origin(run_dir: Path, spec_path: Path, runner: Path) -> dict:
    require(runner.is_file(), f"Origin runner not found: {runner}")
    # The shared Origin runner writes project and figure files without creating
    # their parent directories. Create them in this run's isolated workspace.
    (run_dir / "output" / "opju").mkdir(parents=True, exist_ok=True)
    (run_dir / "output" / "figures").mkdir(parents=True, exist_ok=True)
    config = {"ORIGIN_PYTHON": str(Path(sys.executable).resolve()), "WORKSPACE": str(run_dir),
              "SKILL_DIR": str(runner.parent.parent)}
    config_path = run_dir / "origin_config.json"
    save_json(config_path, config)
    base = [sys.executable, str(runner), "--config", str(config_path)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    check = subprocess.run(base + ["preview", str(spec_path)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
    (run_dir / "origin_preview.log").write_text(check.stdout + check.stderr, encoding="utf-8")
    require(check.returncode == 0, "Origin FigureSpec preview failed; inspect origin_preview.log")
    result = subprocess.run(base + ["run", str(spec_path)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env)
    (run_dir / "origin_run.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, "Origin execution failed; inspect origin_run.log and logs/*/qa.json")
    latest = json.loads((run_dir / "logs" / "latest.json").read_text(encoding="utf-8"))
    qa = json.loads(Path(latest["qa"]).read_text(encoding="utf-8"))
    require(qa.get("status") == "success" and qa.get("checks", {}).get("opju_reopened"),
            "Origin QA did not verify the reopened OPJU")
    require(len(qa.get("analysis", [])) == 1, "Expected one Origin linear fit")
    return qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true", help="extract and cross-check without starting Origin")
    parser.add_argument("--show-origin", action="store_true", help="show the dedicated Origin session while running")
    parser.add_argument("--origin-runner", type=Path,
                        default=Path(__file__).with_name("origin_task_styled.py"))
    args = parser.parse_args()
    require(sys.version_info[:2] == (3, 11) and sys.platform == "win32",
            "Use the installed 64-bit Windows Python 3.11 for OriginPro 2021")
    manifest_path = args.manifest.resolve()
    require(manifest_path.is_file(), f"Manifest not found: {manifest_path}")
    manifest = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8-sig")))
    source_root = manifest_path.parent
    measurement_rows: list[dict] = []
    curves: list[pd.DataFrame] = []
    for index, sample in enumerate(manifest["samples"], 1):
        path, x, y, audit = read_curve(sample, source_root, manifest["columns"])
        y = y * manifest["current_scale"]
        require(np.isfinite(y).all(), f"Current scale overflowed for {path}")
        row, baseline, response = extract(x, y, manifest, str(path))
        measurement_rows.append({"sample": index, "source": str(path), "source_sha256": audit["source_sha256"],
                                 "concentration": number(sample["concentration"], "concentration"),
                                 "row_start": audit["row_slice"][0], "row_stop": audit["row_slice"][1],
                                 "n_points": len(x), **row})
        curves.append(pd.DataFrame({"potential": x, "current": y,
                                    "baseline": baseline, "positive_response": response}))
    measurements = pd.DataFrame(measurement_rows)
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / ("run_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    run_dir.mkdir()
    print(f"RUN_DIR={run_dir}", flush=True)
    curve_paths = []
    for index, frame in enumerate(curves, 1):
        path = run_dir / f"curve_{index:03d}.csv"
        frame.to_csv(path, index=False)
        curve_paths.append(path)
    quality = {**DEFAULT_PEAK_QUALITY, **manifest["peak"].get("quality", {})}
    center = float(measurements["peak_potential"].median())
    deviations = (measurements["peak_potential"] - center).abs()
    aligned = bool((deviations <= quality["max_shift_v"] + 1e-12).all())
    locally_distinct = bool(measurements["peak_quality"].eq("pass").all())
    measurements["peak_shift_from_median_v"] = deviations
    measurements["peak_aligned"] = deviations <= quality["max_shift_v"] + 1e-12
    measurements["quality_status"] = np.where(
        measurements["peak_quality"].eq("pass") & measurements["peak_aligned"], "pass", "reject")
    measurements.to_csv(run_dir / "measurements.csv", index=False)
    quality_report = {
        "status": "pass" if (locally_distinct and aligned) else "reject",
        "criteria": quality,
        "reference_potential_v": center,
        "peak_potential_range_v": [float(measurements["peak_potential"].min()),
                                    float(measurements["peak_potential"].max())],
        "max_deviation_v": float(deviations.max()),
        "all_peaks_distinct": locally_distinct,
        "all_peaks_aligned": aligned,
        "samples": [
            {"source": row["source"], "concentration": row["concentration"],
             "candidate_potential_v": row["peak_potential"], "prominence_snr": row["peak_prominence_snr"],
             "prominence_fraction": row["peak_prominence_fraction"],
             "shift_from_median_v": row["peak_shift_from_median_v"],
             "aligned": bool(row["peak_aligned"]), "status": row["quality_status"],
             "issues": "; ".join(filter(None, [
                 row["peak_quality_issues"],
                 (f"peak shift {row['peak_shift_from_median_v']:.3g} V exceeds {quality['max_shift_v']:g} V"
                  if not row["peak_aligned"] else ""),
             ]))}
            for row in measurements.to_dict("records")
        ],
    }
    save_json(run_dir / "peak_quality.json", quality_report)
    if quality_report["status"] != "pass":
        save_json(run_dir / "analysis.json", {
            "status": "peak_quality_failed", "analyte": manifest["analyte"],
            "manifest": str(manifest_path), "manifest_sha256": digest(manifest_path),
            "quality_report": str(run_dir / "peak_quality.json"),
            "fit_performed": False,
            "reason": "One or more peaks are not sufficiently distinct or their potentials do not align.",
            "output_dir": str(run_dir),
        })
        raise ValueError(f"Peak quality check failed; no sensitivity fit performed. Review {run_dir / 'peak_quality.json'}")
    calibration_rows = []
    for concentration, group in measurements.groupby("concentration", sort=True):
        values = group["delta_current"].to_numpy(dtype=float)
        calibration_rows.append({"concentration": float(concentration), "mean_delta": float(values.mean()),
                                 "sd_delta": float(values.std(ddof=1)) if len(values) >= 2 else math.nan,
                                 "n": len(values)})
    calibration = pd.DataFrame(calibration_rows)
    if "fit_range" in manifest:
        low, high = interval(manifest["fit_range"], "fit_range")
    else:
        low, high = float(calibration["concentration"].min()), float(calibration["concentration"].max())
    selected = calibration[(calibration["concentration"] >= low) & (calibration["concentration"] <= high)].copy()
    outside = calibration[~calibration.index.isin(selected.index)].copy()
    require(len(selected) >= 3, "Fit range must contain at least three distinct concentrations")
    xfit = selected["concentration"].to_numpy(dtype=float)
    yfit = selected["mean_delta"].to_numpy(dtype=float)
    slope, intercept = (float(v) for v in np.polyfit(xfit, yfit, 1))
    residual = yfit - (slope * xfit + intercept)
    sst = float(np.sum((yfit - yfit.mean()) ** 2))
    r2 = 1 - float(np.sum(residual ** 2)) / sst if sst > 0 else None
    calibration.to_csv(run_dir / "calibration.csv", index=False)
    spec = make_spec(manifest, run_dir, curve_paths, calibration, selected, outside)
    spec["runtime"]["show_origin"] = bool(args.show_origin)
    spec_path = run_dir / "figure_spec.json"
    save_json(spec_path, spec)
    report = {
        "status": "prepared", "analyte": manifest["analyte"], "manifest": str(manifest_path),
        "manifest_sha256": digest(manifest_path), "peak": manifest["peak"], "baseline": manifest["baseline"],
        "fit_range": [low, high], "fit_levels": len(selected), "replicates": len(measurements),
        "fit_policy": "unweighted concentration means; free intercept; no automatic point exclusion",
        "python_crosscheck": {"slope": slope, "intercept": intercept, "r_squared": r2},
        "concentration_unit": manifest["concentration_unit"],
        "current_unit": manifest["current_unit"],
        "K_unit": f"{manifest['current_unit']}/{manifest['concentration_unit']}",
        "source_current_unit": manifest.get("source_current_unit", manifest["current_unit"]),
        "current_scale": manifest["current_scale"],
        "sources": [{"path": row["source"], "sha256": row["source_sha256"]} for row in measurement_rows],
        "output_dir": str(run_dir),
    }
    if "electrode_area_cm2" in manifest:
        report["electrode_area_cm2"] = number(manifest["electrode_area_cm2"], "electrode_area_cm2")
    report_path = run_dir / "analysis.json"
    save_json(report_path, report)
    if args.prepare_only:
        print("Prepared only: Origin was not started.")
        return
    try:
        qa = run_origin(run_dir, spec_path, args.origin_runner.resolve())
        origin_fit = qa["analysis"][0]
        require(math.isclose(origin_fit["slope"], slope, rel_tol=1e-8, abs_tol=1e-10) and
                math.isclose(origin_fit["intercept"], intercept, rel_tol=1e-8, abs_tol=1e-10),
                "Origin fit differs from independent Python cross-check")
        k = float(origin_fit["slope"])
        report.update(status="success", K=k, K_magnitude=abs(k),
                      intercept=float(origin_fit["intercept"]), r_squared=origin_fit["r_squared"],
                      K_standard_error=origin_fit["native_result"].get("slope_error"),
                      origin_engine=origin_fit["engine"], origin_qa=str(run_dir / "logs" / qa["run_id"] / "qa.json"),
                      origin_files=[item["path"] for item in qa["files"]])
        if "electrode_area_cm2" in report:
            report["area_normalized_K"] = k / report["electrode_area_cm2"]
            report["area_normalized_K_unit"] = report["K_unit"] + "/cm^2"
        report["reference_style_files"] = render_reference_figure(report, calibration, run_dir)
        report["top_level_delivery_files"] = publish_delivery_copies(report, qa, root)
        report["figure_generation"] = {
            "fit_engine": "Native Origin fitLR",
            "native_companion_engine": "Native Origin graph export",
            "presentation_engine": "Script-drawn SVG rendered to PNG",
            "generative_image_ai_used": False,
            "measured_data_and_predictions_distinguished": True,
        }
    except Exception as exc:
        report.update(status="figure_failed" if "K" in report else "origin_failed", error=str(exc))
        save_json(report_path, report)
        raise
    save_json(report_path, report)
    print(f"K={report['K']:.10g} {plot_unit(report['K_unit'])}; R2={report['r_squared']}; Origin OPJU verified")


if __name__ == "__main__":
    main()
