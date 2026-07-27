#!/usr/bin/env python3
"""
urban-heat-analysis: Urban Heat Island (UHI) Intensity Calculator
===================================================================
Calculate UHI intensity from MODIS LST GeoTIFF data and classify
heat island levels.

Privacy Disclosure:
- This tool processes data locally. No data is sent to any server.
- When using optional NASA POWER air temperature validation, coordinates
  and date range are sent to power.larc.nasa.gov via HTTPS.

Data Source:
- MODIS LST (MOD11A1/MYD11A1) — NASA EOSDIS, Public Domain
- NASA POWER (optional) — Public Domain

License: MIT-0 (No attribution required)
Author: ruiduobao
Version: 0.1.0
"""

import argparse
import sys
import os
import json
import csv
from typing import Optional, Tuple, Dict, List
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("ERROR: 'numpy' is required. Install with: pip install numpy>=1.21.0")
    sys.exit(1)

try:
    import rasterio
    from rasterio.transform import from_bounds
except ImportError:
    print("ERROR: 'rasterio' is required. Install with: pip install rasterio>=1.3.0")
    print("  Note: rasterio requires GDAL. On Windows, use: conda install -c conda-forge rasterio")
    sys.exit(1)


# ============================================================
# Place resolver (v0.2.0 — batch2 upgrade)
# ============================================================

def _resolve_place(place: str):
    """Resolve a Chinese place name to bbox + centroid."""
    import os as _os
    import sys as _sys

    candidates = [
        _os.path.join(_os.path.dirname(__file__), "..", "..", "_shared"),
        _os.path.join(_os.getcwd(), "_shared"),
    ]
    for c in candidates:
        full = _os.path.abspath(c)
        if _os.path.isdir(full) and _os.path.isfile(_os.path.join(full, "place_resolver.py")):
            if full not in _sys.path:
                _sys.path.insert(0, full)
            try:
                import place_resolver  # type: ignore
                return place_resolver.resolve_place(place)
            except Exception:
                continue
    raise ValueError(f"无法解析地点 '{place}' (place_resolver unavailable)")


# ============================================================
# Constants
# ============================================================

UHI_CLASSES = [
    (4.0, float("inf"), "Strong UHI"),
    (2.0, 4.0, "Moderate UHI"),
    (0.0, 2.0, "Weak UHI"),
    (float("-inf"), 0.0, "None/Cool"),
]

# MODIS LST scale factor: value * 0.02 = Kelvin
MODIS_LST_SCALE = 0.02
KELVIN_TO_CELSIUS = -273.15

# Presets (v0.2.0)
PRESETS = {
    "uhi-china-summer": {
        "description": "中国典型夏季城市热岛（MODIS LST）",
        "lst_scale": 0.02,
        "rural_fraction": 0.10,
    },
    "uhi-china-tight-rural": {
        "description": "中国城市热岛（更严格的乡村参考，像素取最低 5%）",
        "lst_scale": 0.02,
        "rural_fraction": 0.05,
    },
    "uhi-china-loose-rural": {
        "description": "中国城市热岛（更宽松的乡村参考，像素取最低 20%）",
        "lst_scale": 0.02,
        "rural_fraction": 0.20,
    },
}


# ============================================================
# Core Functions
# ============================================================

def lst_to_celsius(data: np.ndarray, scale: float = MODIS_LST_SCALE,
                   offset: float = 0.0) -> np.ndarray:
    """Convert raw LST values to Celsius.

    MODIS LST: value * 0.02 = Kelvin, then K - 273.15 = Celsius.
    """
    return data.astype(np.float64) * scale + offset + KELVIN_TO_CELSIUS


def read_lst_geotiff(filepath: str) -> Tuple[np.ndarray, dict]:
    """Read LST GeoTIFF and return data in Celsius plus metadata.

    Args:
        filepath: Path to LST GeoTIFF file

    Returns:
        (data_celsius, metadata_dict)
    """
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float64)
        nodata = src.nodata
        profile = src.profile.copy()
        bounds = src.bounds
        crs = str(src.crs)

    # Mask nodata
    if nodata is not None:
        data[data == nodata] = np.nan

    # Convert to Celsius
    data_celsius = lst_to_celsius(data)

    # Mask unreasonable values (outside -50 to 70 C)
    data_celsius[(data_celsius < -50) | (data_celsius > 70)] = np.nan

    metadata = {
        "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "crs": crs,
        "shape": data_celsius.shape,
        "profile": profile,
    }

    valid_count = np.sum(~np.isnan(data_celsius))
    total_count = data_celsius.size
    print(f"  LST range: {np.nanmin(data_celsius):.1f} to {np.nanmax(data_celsius):.1f} °C")
    print(f"  Valid pixels: {valid_count}/{total_count} ({valid_count/total_count*100:.1f}%)")

    return data_celsius, metadata


def compute_uhi(lst_data: np.ndarray, rural_mask: Optional[np.ndarray] = None,
                rural_fraction: float = 0.1) -> Tuple[np.ndarray, float]:
    """Compute UHI intensity map.

    Args:
        lst_data: LST in Celsius (2D array)
        rural_mask: Boolean mask of rural reference pixels (optional)
        rural_fraction: Fraction of coolest pixels to use as rural reference
                        if no mask provided (default 10%)

    Returns:
        (uhi_intensity, rural_reference_temperature)
    """
    valid_data = lst_data[~np.isnan(lst_data)]

    if len(valid_data) == 0:
        print("ERROR: No valid LST data.")
        sys.exit(1)

    if rural_mask is not None:
        # Use provided mask
        rural_pixels = lst_data[rural_mask & ~np.isnan(lst_data)]
        if len(rural_pixels) == 0:
            print("ERROR: Rural mask contains no valid pixels.")
            sys.exit(1)
        t_rural = float(np.nanmean(rural_pixels))
        print(f"  Rural reference (mask): {t_rural:.2f} °C ({len(rural_pixels)} pixels)")
    else:
        # Use lowest N% of pixels as rural reference
        n_rural = max(1, int(len(valid_data) * rural_fraction))
        sorted_temps = np.sort(valid_data)
        t_rural = float(np.mean(sorted_temps[:n_rural]))
        print(f"  Rural reference (bottom {rural_fraction*100:.0f}%): {t_rural:.2f} °C ({n_rural} pixels)")

    uhi = lst_data - t_rural

    return uhi, t_rural


def classify_uhi(uhi_data: np.ndarray) -> np.ndarray:
    """Classify UHI intensity into levels.

    Returns:
        Integer array: 0=None/Cool, 1=Weak, 2=Moderate, 3=Strong
    """
    classified = np.full(uhi_data.shape, 0, dtype=np.uint8)
    classified[(uhi_data >= 0) & (uhi_data < 2)] = 1   # Weak
    classified[(uhi_data >= 2) & (uhi_data < 4)] = 2   # Moderate
    classified[(uhi_data >= 4)] = 3                    # Strong

    # Keep nodata as 255
    classified[np.isnan(uhi_data)] = 255

    return classified


def compute_statistics(uhi_data: np.ndarray, classified: np.ndarray) -> Dict:
    """Compute UHI statistics."""
    valid = uhi_data[~np.isnan(uhi_data)]

    if len(valid) == 0:
        return {"error": "No valid data"}

    stats = {
        "uhi_intensity": {
            "mean": round(float(np.nanmean(valid)), 3),
            "std": round(float(np.nanstd(valid)), 3),
            "min": round(float(np.nanmin(valid)), 3),
            "max": round(float(np.nanmax(valid)), 3),
            "median": round(float(np.nanmedian(valid)), 3),
        },
        "classification_percentages": {},
        "area_km2": {},
    }

    # Classification percentages
    total_valid = np.sum(~np.isnan(uhi_data))
    class_names = {0: "None/Cool", 1: "Weak UHI", 2: "Moderate UHI", 3: "Strong UHI"}
    for cls_id, name in class_names.items():
        count = np.sum(classified == cls_id)
        pct = count / total_valid * 100 if total_valid > 0 else 0
        stats["classification_percentages"][name] = round(float(pct), 2)

    return stats


def write_geotiff(data: np.ndarray, output_path: str, reference_profile: dict,
                  dtype: str = "float32", nodata: float = -9999):
    """Write GeoTIFF output."""
    profile = reference_profile.copy()
    profile.update(
        dtype=dtype,
        count=1,
        nodata=nodata,
        compress="lzw",
    )

    # Handle nodata for float vs int
    if dtype == "uint8":
        write_data = data.astype(np.uint8)
    else:
        write_data = data.astype(np.float32)
        write_data[np.isnan(write_data)] = nodata

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(write_data, 1)

    print(f"  Saved: {output_path}")


# ============================================================
# Temporal Analysis
# ============================================================

def temporal_analysis(lst_dir: str, rural_mask_path: Optional[str] = None) -> List[Dict]:
    """Analyze UHI across multiple LST files (temporal analysis).

    Groups files by season and computes mean UHI per season.
    """
    lst_files = sorted(Path(lst_dir).glob("*.tif*"))
    if not lst_files:
        lst_files = sorted(Path(lst_dir).glob("*.TIF"))

    if not lst_files:
        print(f"ERROR: No GeoTIFF files found in {lst_dir}")
        sys.exit(1)

    print(f"Found {len(lst_files)} LST files.")

    rural_mask = None
    if rural_mask_path:
        with rasterio.open(rural_mask_path) as src:
            rural_mask = src.read(1).astype(bool)

    seasonal_results = {}
    months_to_season = {
        12: "Winter", 1: "Winter", 2: "Winter",
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Autumn", 10: "Autumn", 11: "Autumn",
    }

    for fpath in lst_files:
        fname = fpath.name
        # Try to extract date from filename (common MODIS naming)
        # MOD11A1.A2020001... or generic date patterns
        lst_data, metadata = read_lst_geotiff(str(fpath))
        uhi, t_rural = compute_uhi(lst_data, rural_mask)

        # Extract month from filename or use 0
        month = 0
        for i in range(len(fname) - 3):
            if fname[i:i+4].isdigit() and fname[i:i+4].startswith(("19", "20")):
                # Try YYYYDDD or YYYYMM
                if len(fname) > i + 7 and fname[i+4:i+8].isdigit():
                    # YYYYDDD format (MODIS)
                    doy = int(fname[i+4:i+8])
                    from datetime import datetime
                    try:
                        dt = datetime.strptime(f"{fname[i:i+4]}{doy}", "%Y%j")
                        month = dt.month
                    except ValueError:
                        pass
                    break

        season = months_to_season.get(month, "Unknown")

        if season not in seasonal_results:
            seasonal_results[season] = []

        valid_uhi = uhi[~np.isnan(uhi)]
        seasonal_results[season].append({
            "file": fname,
            "mean_uhi": round(float(np.nanmean(valid_uhi)), 3),
            "max_uhi": round(float(np.nanmax(valid_uhi)), 3),
            "t_rural": round(float(t_rural), 3),
        })

    # Aggregate by season
    summary = []
    season_order = ["Spring", "Summer", "Autumn", "Winter", "Unknown"]
    for season in season_order:
        if season in seasonal_results:
            records = seasonal_results[season]
            mean_uhis = [r["mean_uhi"] for r in records]
            summary.append({
                "season": season,
                "n_images": len(records),
                "mean_uhi": round(float(np.mean(mean_uhis)), 3),
                "max_mean_uhi": round(float(np.max(mean_uhis)), 3),
                "min_mean_uhi": round(float(np.min(mean_uhis)), 3),
            })

    return summary


# ============================================================
# CLI Subcommands
# ============================================================

def cmd_analyze(args):
    """Compute UHI intensity from LST data."""
    # Apply preset
    if getattr(args, "preset", None):
        ps = PRESETS[args.preset]
        print(f"[preset] {args.preset}: {ps['description']}")
        if args.rural_fraction == 0.1:
            args.rural_fraction = ps["rural_fraction"]

    # Resolve place (just print for context; do not auto-fetch MODIS LST yet)
    place_info = None
    if getattr(args, "place", None):
        try:
            place_info = _resolve_place(args.place)
            print(f"[place] {args.place} -> {place_info.resolved_name} (bbox={place_info.bbox})")
        except ValueError as e:
            print(f"WARN: {e}")
            place_info = None

    print(f"Reading LST data: {args.lst}")
    lst_data, metadata = read_lst_geotiff(args.lst)

    rural_mask = None
    if args.rural_mask:
        print(f"Reading rural mask: {args.rural_mask}")
        with rasterio.open(args.rural_mask) as src:
            rural_mask = src.read(1).astype(bool)
        print(f"  Rural pixels: {np.sum(rural_mask)}")

    uhi, t_rural = compute_uhi(lst_data, rural_mask, args.rural_fraction)

    # Statistics
    classified = classify_uhi(uhi)
    stats = compute_statistics(uhi, classified)

    # Output
    output_path = args.output or "uhi_intensity.tif"
    write_geotiff(uhi, output_path, metadata["profile"])

    # Resolve --format (new) vs --json (deprecated) for stats sidecar
    fmt = getattr(args, "fmt", None)
    if fmt is None:
        if getattr(args, "json", False):
            fmt = "json"
        else:
            fmt = "json"

    base = (args.output or "uhi_intensity.tif").replace(".tif", "")
    if fmt == "csv":
        stats_path = base + "_stats.csv"
    else:
        stats_path = base + "_stats.json"
    stats["rural_reference_temp_c"] = round(t_rural, 3)
    stats["place"] = getattr(args, "place", None)
    if place_info is not None:
        stats["place_info"] = place_info.to_dict()
    stats["preset"] = getattr(args, "preset", None)
    if fmt == "csv":
        # Flatten stats into a small CSV: one row per classification bucket
        # plus key metrics in sidecar comment
        with open(stats_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["metric", "value"])
            w.writerow(["uhi_mean", stats["uhi_intensity"]["mean"]])
            w.writerow(["uhi_std", stats["uhi_intensity"]["std"]])
            w.writerow(["uhi_min", stats["uhi_intensity"]["min"]])
            w.writerow(["uhi_max", stats["uhi_intensity"]["max"]])
            w.writerow(["uhi_median", stats["uhi_intensity"]["median"]])
            w.writerow(["rural_reference_temp_c", stats["rural_reference_temp_c"]])
            for name, pct in stats["classification_percentages"].items():
                w.writerow([f"class_{name}", pct])
    else:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\nStatistics saved to: {stats_path} (format={fmt})")
    print(f"  Mean UHI: {stats['uhi_intensity']['mean']:.2f} °C")
    print(f"  Max UHI: {stats['uhi_intensity']['max']:.2f} °C")
    for name, pct in stats["classification_percentages"].items():
        print(f"  {name}: {pct:.1f}%")


def cmd_classify(args):
    """Classify existing UHI intensity GeoTIFF."""
    print(f"Reading UHI data: {args.uhi_tif}")
    with rasterio.open(args.uhi_tif) as src:
        uhi_data = src.read(1).astype(np.float64)
        nodata = src.nodata
        profile = src.profile.copy()

    if nodata is not None:
        uhi_data[uhi_data == nodata] = np.nan

    classified = classify_uhi(uhi_data)
    stats = compute_statistics(uhi_data, classified)

    output_path = args.output or "uhi_classified.tif"
    write_geotiff(classified, output_path, profile, dtype="uint8", nodata=255)

    # Print classification summary
    print("\nClassification Summary:")
    class_names = {0: "None/Cool", 1: "Weak UHI", 2: "Moderate UHI", 3: "Strong UHI"}
    for cls_id, name in class_names.items():
        pct = stats["classification_percentages"].get(name, 0)
        print(f"  {name}: {pct:.1f}%")


def cmd_temporal(args):
    """Temporal UHI analysis across multiple LST files."""
    print(f"Scanning directory: {args.lst_dir}")
    summary = temporal_analysis(args.lst_dir, args.rural_mask)

    output_path = args.output or "uhi_temporal.json"
    # Resolve --format (new) vs --json (deprecated) vs suffix
    fmt = getattr(args, "fmt", None)
    if fmt is None:
        if getattr(args, "json", False):
            fmt = "json"
        else:
            fmt = "json" if output_path.lower().endswith(".json") else "csv"
    if fmt == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
    else:
        if not summary:
            # Write an empty CSV with just the header
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["season", "n_images", "mean_uhi", "max_mean_uhi", "min_mean_uhi"])
                writer.writeheader()
        else:
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["season", "n_images", "mean_uhi", "max_mean_uhi", "min_mean_uhi"],
                )
                writer.writeheader()
                writer.writerows(summary)

    print(f"\nTemporal analysis saved to: {output_path} (format={fmt})")
    print("\nSeasonal UHI Summary:")
    print(f"{'Season':<10} {'Images':<10} {'Mean UHI':<12} {'Max UHI':<12}")
    print("-" * 44)
    for s in summary:
        print(f"{s['season']:<10} {s['n_images']:<10} {s['mean_uhi']:<12.2f} {s['max_mean_uhi']:<12.2f}")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        prog="urban-heat-analysis",
        description="Urban Heat Island (UHI) Intensity Calculator — Analyze heat islands from MODIS LST data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compute UHI from single LST image
  python urban-heat-analysis.py analyze --lst MOD11A1.A2020001.tif --output uhi.tif

  # With rural reference mask
  python urban-heat-analysis.py analyze --lst lst.tif --rural-mask rural.tif --output uhi.tif

  # Classify UHI intensity map
  python urban-heat-analysis.py classify --uhi-tif uhi.tif --output classified.tif

  # Temporal analysis
  python urban-heat-analysis.py temporal --lst-dir ./lst_data/ --output seasonal.json

UHI Classification:
  > 4.0 °C   : Strong UHI
  2.0-4.0 °C : Moderate UHI
  0.0-2.0 °C : Weak UHI
  < 0.0 °C   : None/Cool island
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # --- analyze ---
    analyze_parser = subparsers.add_parser("analyze", help="Compute UHI intensity from LST")
    analyze_parser.add_argument("--lst", required=True, help="LST GeoTIFF file path")
    analyze_parser.add_argument("--rural-mask", help="Rural reference mask GeoTIFF (1=rural, 0=other)")
    analyze_parser.add_argument("--rural-fraction", type=float, default=0.1,
                                help="Fraction of coolest pixels as rural ref (default: 0.1)")
    analyze_parser.add_argument("--place", help="Place name (Chinese or English); for context only")
    analyze_parser.add_argument("--preset", choices=list(PRESETS.keys()),
                                help="Use a preset (uhi-china-summer, uhi-china-tight-rural, ...)")
    analyze_parser.add_argument("--output", help="Output GeoTIFF path")
    analyze_parser.add_argument("--format", dest="fmt", choices=["csv", "json"], default=None,
                                help="Stats sidecar format: json (default) or csv")
    analyze_parser.add_argument("--json", action="store_true",
                                help="[deprecated] Shorthand for --format json (kept for backward compat)")
    analyze_parser.set_defaults(func=cmd_analyze)

    # --- classify ---
    classify_parser = subparsers.add_parser("classify", help="Classify UHI intensity levels")
    classify_parser.add_argument("--uhi-tif", required=True, help="UHI intensity GeoTIFF")
    classify_parser.add_argument("--output", help="Output classified GeoTIFF path")
    classify_parser.set_defaults(func=cmd_classify)

    # --- temporal ---
    temporal_parser = subparsers.add_parser("temporal", help="Temporal UHI analysis")
    temporal_parser.add_argument("--lst-dir", required=True, help="Directory of LST GeoTIFF files")
    temporal_parser.add_argument("--rural-mask", help="Rural reference mask GeoTIFF")
    temporal_parser.add_argument("--output", help="Output JSON path")
    temporal_parser.add_argument("--format", dest="fmt", choices=["csv", "json"], default=None,
                                 help="Output format: json (default) or csv. "
                                      "If omitted, inferred from --output suffix.")
    temporal_parser.add_argument("--json", action="store_true",
                                 help="[deprecated] Shorthand for --format json (kept for backward compat)")
    temporal_parser.set_defaults(func=cmd_temporal)

    # --- from-place: 一句话完成"下载 + UHI 算" ---
    fp_parser = subparsers.add_parser(
        "from-place",
        help="One-line UHI: --place + --start + --end → fetch MODIS LST from PC + compute UHI. "
             "Note: uses modis-11A2-061 (8-day composite, 1km) by default; for daily LST first run modis-lst-download.",
    )
    fp_parser.add_argument("--place", required=True, help="行政区名 (中文/English) → bbox")
    fp_parser.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    fp_parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    fp_parser.add_argument("--dataset", default="modis-11A2-061",
                          choices=["modis-11A2-061"],
                          help="STAC collection (default modis-11A2-061 8-day LST composite)")
    fp_parser.add_argument("--limit", type=int, default=4, help="最多取几景 (default 4)")
    fp_parser.add_argument("--buffer-deg", type=float, default=0.5,
                          help="Buffer (degrees) around resolved point (default 0.5°)")
    fp_parser.add_argument("--rural-fraction", type=float, default=0.1)
    fp_parser.add_argument("--cache-dir", default="./uhi_from_stac_cache")
    fp_parser.add_argument("--no-nominatim", action="store_true")
    fp_parser.add_argument("--output", required=True, help="输出 UHI GeoTIFF 路径")
    fp_parser.add_argument("--qa", action="store_true", help="写出 QA JSON")
    fp_parser.add_argument("--format", dest="qa_fmt", choices=["csv", "json"], default="json",
                           help="QA sidecar format (default: json)")
    fp_parser.set_defaults(func=cmd_from_place)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    return args.func(args)


# ============================================================
# from-place: fetch MODIS LST + compute UHI
# ============================================================
def cmd_from_place(args):
    """One-line UHI: resolve --place via geoskill_core.aoi + fetch MODIS LST + compute UHI.

    [PHASE 1+ 2026-07-26 REFACTOR]
    Step 1: _geoskill_core.aoi.resolve_place(place) → bbox
    Step 2: subprocess 调 modis-lst-download 拉 LST
    Step 3: 调本 skill cmd_analyze
    """
    import os as _os
    import sys as _sys
    import subprocess as _sp

    skill_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    gk_dir = _os.path.join(skill_dir, "_geoskill_core")
    if not _os.path.isdir(gk_dir):
        print("ERROR: _geoskill_core not vendored. Run vendor.py.", file=sys.stderr)
        return 3
    if skill_dir not in _sys.path:
        _sys.path.insert(0, skill_dir)
    try:
        from _geoskill_core import aoi as _aoi
    except Exception as _e:
        print(f"ERROR: failed to import _geoskill_core.aoi: {_e}", file=sys.stderr)
        return 3
    try:
        m = _aoi.resolve_place(args.place, allow_nominatim=not args.no_nominatim, use_cache=False)
    except Exception as _e:
        print(f"ERROR: failed to resolve --place={args.place!r}: {_e}", file=sys.stderr)
        return 5
    bbox = m.bbox_wgs84
    if not bbox or len(bbox) != 4:
        print(f"ERROR: invalid bbox: {bbox}", file=sys.stderr)
        return 5
    print(f"[from-place] resolved {args.place!r} → bbox={bbox} (resolver={m.resolver})",
          file=sys.stderr)
    # Step 2: 调 modis-lst-download
    parent = _os.path.dirname(skill_dir)
    fetch_dir = _os.path.join(parent, "modis-lst-download")
    fetch_script = _os.path.join(fetch_dir, "scripts", "modis_lst_download.py")
    if not _os.path.isfile(fetch_script):
        # fallback
        for cand in [_os.path.join(fetch_dir, "modis_lst_download.py"),
                      _os.path.join(fetch_dir, "modis-lst-download.py")]:
            if _os.path.isfile(cand):
                fetch_script = cand
                break
    if not _os.path.isfile(fetch_script):
        print(f"ERROR: modis-lst-download script not found at {fetch_dir}", file=sys.stderr)
        return 3
    out_dir = _os.path.dirname(args.output) or "."
    cache_dir = _os.path.join(out_dir, ".from_place_cache")
    _os.makedirs(cache_dir, exist_ok=True)
    cmd = [
        _sys.executable, fetch_script, "download",
        "--bbox", str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
        "--start", args.start,
        "--end", args.end,
        "--product", "MOD11A1",  # 1km daily LST
        "--layers", "LST_Day_1km,QC_Day",
        "--output", cache_dir,
    ]
    print(f"[from-place] invoking: {' '.join(cmd)}", file=sys.stderr)
    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=600)
    except _sp.TimeoutExpired:
        print("ERROR: modis-lst-download timeout (600s)", file=sys.stderr)
        return 4
    except Exception as _e:
        print(f"ERROR: modis-lst-download failed: {_e}", file=sys.stderr)
        return 7
    if r.returncode != 0:
        print(f"ERROR: modis-lst-download exit {r.returncode}:\n{r.stderr[-500:]}",
              file=sys.stderr)
        return r.returncode
    # 找 LST .tif
    lst_files = []
    for root, _, files in _os.walk(cache_dir):
        for f in files:
            if f.endswith(".tif") and "LST" in f.upper() and not f.endswith(".part"):
                lst_files.append(_os.path.join(root, f))
    if not lst_files:
        print(f"ERROR: no LST .tif produced in {cache_dir}", file=sys.stderr)
        return 5
    # Step 3: 调本 skill analyze
    analyze_args = argparse.Namespace(
        lst=lst_files, output=args.output, bbox=bbox, place=args.place,
        urban_buffer_km=getattr(args, "urban_buffer_km", 5.0),
        rural_buffer_km=getattr(args, "rural_buffer_km", 15.0),
        day_night=getattr(args, "day_night", "day"),
        qa=getattr(args, "qa", False),
    )
    return cmd_analyze(analyze_args)

    _shared_path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
        "_shared", "from_stac.py",
    )
    if not _os.path.exists(_shared_path):
        print(f"ERROR: shared helper not found at {_shared_path}", file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location("from_stac", _shared_path)
    fs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fs)
    if not fs.is_available():
        print("ERROR: requires: pip install planetary-computer pystac-client rasterio",
              file=sys.stderr)
        return 2

    try:
        meta = fs.fetch_scenes(
            place=args.place,
            start=args.start,
            end=args.end,
            dataset=args.dataset,
            bands=["LST_Day_1km"],
            max_cloud=100.0,  # LST no cloud filter
            limit=args.limit,
            output_dir=args.cache_dir,
            no_nominatim=args.no_nominatim,
            buffer_deg=args.buffer_deg,
            quiet=False,
        )
    except Exception as e:
        print(f"ERROR: fetch_scenes failed: {e}", file=sys.stderr)
        return 1

    print(f"[from-place] fetched {meta['count']} MODIS LST scene(s) for {args.place!r} "
          f"({args.start}..{args.end})", file=sys.stderr)

    # Mean-composite all fetched LST scenes (simple average; QA-skip nodata)
    arrs = []
    ref_profile = None
    for s in meta["scenes"]:
        path = s["asset_paths"].get("LST_Day_1km")
        if not path or not _os.path.exists(path):
            print(f"WARNING: missing LST_Day_1km for {s['id']}, skipping", file=sys.stderr)
            continue
        with rasterio.open(path) as src:
            data = src.read(1).astype("float32")
            # MODIS LST scale = 0.02 (K). Convert to °C.
            data = data * 0.02 - 273.15
            nodata = src.nodata if src.nodata is not None else 0
            data[data == nodata] = np.nan
            arrs.append(data)
            if ref_profile is None:
                ref_profile = src.profile.copy()

    if not arrs:
        print("ERROR: no usable LST scenes after fetch", file=sys.stderr)
        return 1

    # Reproject all to reference grid if needed
    from rasterio.warp import reproject as _reproj
    aligned = []
    for i, a in enumerate(arrs):
        if i == 0:
            aligned.append(a)
            continue
        dst = np.full_like(a, np.nan)
        _reproj(
            source=a, destination=dst,
            src_transform=ref_profile["transform"], src_crs=ref_profile["crs"],
            dst_transform=ref_profile["transform"], dst_crs=ref_profile["crs"],
            resampling=Resampling.bilinear,
        )
        aligned.append(dst)
    mean_lst = np.nanmean(np.stack(aligned), axis=0)
    mean_lst = np.where(np.isnan(mean_lst), 0.0, mean_lst).astype("float32")

    # Compute UHI using same logic as cmd_analyze
    flat = mean_lst.flatten()
    valid = flat[flat > -50]  # filter sentinel 0 / nodata
    if valid.size == 0:
        print("ERROR: no valid LST pixels", file=sys.stderr)
        return 1
    sorted_v = np.sort(valid)
    n = int(args.rural_fraction * len(sorted_v))
    n = max(1, n)
    rural_ref = float(np.mean(sorted_v[:n]))
    uhi = mean_lst - rural_ref

    # Write output
    out_profile = ref_profile.copy()
    out_profile.update(dtype="float32", count=1, nodata=-9999.0, compress="lzw")
    with rasterio.open(args.output, "w", **out_profile) as dst:
        dst.write(np.where(np.isnan(uhi), -9999.0, uhi).astype("float32"), 1)

    print(f"[from-place] UHI written to {args.output} (rural_ref={rural_ref:.2f}°C)", file=sys.stderr)

    if getattr(args, "qa", False):
        qa_fmt = getattr(args, "qa_fmt", "json")
        if qa_fmt == "csv":
            qa_path = args.output + ".qa.csv"
            import csv as _csv
            with open(qa_path, "w", encoding="utf-8", newline="") as f:
                w = _csv.writer(f)
                w.writerow(["key", "value"])
                w.writerow(["skill", "urban-heat-analysis"])
                w.writerow(["version", "0.2.0"])
                w.writerow(["command", "from-place"])
                w.writerow(["place", str(meta.get("place"))])
                w.writerow(["bbox", str(meta.get("bbox"))])
                w.writerow(["dataset", meta.get("dataset")])
                w.writerow(["start", args.start])
                w.writerow(["end", args.end])
                w.writerow(["scenes_used", len(arrs)])
                w.writerow(["rural_ref_celsius", rural_ref])
                w.writerow(["uhi_mean_celsius", float(np.nanmean(uhi))])
                w.writerow(["uhi_max_celsius", float(np.nanmax(uhi))])
                w.writerow(["output", args.output])
        else:
            qa_path = args.output + ".qa.json"
            import json
            qa = {
                "skill": "urban-heat-analysis",
                "version": "0.2.0",
                "command": "from-place",
                "place": meta["place"],
                "bbox": meta["bbox"],
                "dataset": meta["dataset"],
                "start": args.start,
                "end": args.end,
                "scenes_used": len(arrs),
                "scene_ids": [s["id"] for s in meta["scenes"]],
                "rural_ref_celsius": rural_ref,
                "uhi_mean_celsius": float(np.nanmean(uhi)),
                "uhi_max_celsius": float(np.nanmax(uhi)),
                "output": args.output,
            }
            with open(qa_path, "w", encoding="utf-8") as f:
                json.dump(qa, f, ensure_ascii=False, indent=2)
        print(f"[from-place] QA written to {qa_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
