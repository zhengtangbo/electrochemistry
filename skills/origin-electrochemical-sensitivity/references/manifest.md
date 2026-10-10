# Input manifest

Create one JSON file **per peak or trough**. The runner measures only one feature per manifest; for multiple qualifying features, use separate manifests and case folders as described in `SKILL.md`. Paths under `samples` are relative to this manifest unless absolute. Every source must contain a header row. The helper accepts CSV, TSV, TXT, DAT, XLSX, and XLSM; `separator`, `skiprows`, and `sheet` can be set per sample when needed. `row_slice` is optional `[start, stop]` with zero-based, stop-exclusive row numbers, useful for selecting one CV sweep.

```json
{
  "analyte": "analyte name",
  "concentration_unit": "mM",
  "current_unit": "uA",
  "potential_unit": "V",
  "columns": {"x": "Potential", "y": "Current"},
  "peak": {"direction": "up", "window": [0.2, 0.4],
           "quality": {"min_prominence_snr": 5, "min_prominence_fraction": 0.25,
                       "max_shift_v": 0.03}},
  "baseline": {"mode": "linear", "windows": [[0.1, 0.16], [0.44, 0.5]]},
  "electrode_area_cm2": 0.07,
  "fit_range": [0, 2],
  "samples": [
    {"path": "blank.csv", "concentration": 0},
    {"path": "low.csv", "concentration": 0.5},
    {"path": "medium.csv", "concentration": 1},
    {"path": "high.csv", "concentration": 2}
  ]
}
```

`peak.direction` is `up` for an oxidation peak or `down` for a reduction trough. `baseline.mode` is `linear` with exactly two windows on opposite sides of the peak, or `constant` with exactly one window outside the peak. The windows and current convention apply to every curve. `fit_range` and `electrode_area_cm2` are optional; omitted `fit_range` fits all concentrations, and omitted area skips area normalization. Do not set a linear range based only on maximizing R². At least three distinct concentrations must remain in the fit. Multiple sample entries at the same concentration are replicates; the fit uses their mean response without implicit weighting.

Each measured peak is chosen from the raw points after baseline correction; no smoothing or interpolation of the peak is performed. The output includes the selected peak potential and both measured and baseline current so that each `delta_current` can be checked. If the signal has a different baseline convention, peak overlap, or a significant blank response that must be subtracted, use a reviewed task-specific method instead of changing these definitions silently.

The `quality` settings are optional; the values above are the defaults. `min_prominence_snr` compares the peak's rise above both shoulders of the common search window with the RMS deviation in baseline anchor points. `min_prominence_fraction` requires that rise to be at least a fraction of the candidate peak-to-baseline response. `max_shift_v` is the largest allowed absolute deviation of any candidate's potential from the median candidate potential. The run rejects all sensitivity fitting if even one curve has an indistinct peak or the candidates do not align. Candidate measurements and `peak_quality.json` remain available for review. These thresholds are screening rules, not a substitute for inspecting the raw shapes; do not weaken them post hoc to manufacture a result.

If the file stores current in one unit but the plot should use another, set optional `source_current_unit` and `current_scale` at the top level. For example, source `i(A/cm²)` can be plotted as `µA/cm²` with `"source_current_unit": "A/cm²"`, `"current_scale": 1000000`, and `"current_unit": "µA/cm²"`. The helper multiplies every raw current value by this factor before baseline/peak analysis and records the factor in `analysis.json`; it never overwrites the source files. Omit the factor for a 1:1 unit mapping. Do not divide a current-density source by electrode area again.

For a passing analysis, the editable Origin graph and its PNG/PDF exports use the same reference layout as the additional SVG/PNG: a four-sided black frame without top/right ticks, black square points, a thin red fit line, and the actual K and R² in the lower-right plot. The annotations are part of the saved OPJU and are verified after reopening. The SVG/PNG are rendered separately from the same verified Origin coefficients, not from a second fit. Review all delivered image formats visually; no default-style export should be mixed with the reference-style figure.
