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

    # Write statistics JSON
    stats_path = args.output.replace(".tif", "_stats.json") if args.output else "uhi_stats.json"
    stats["rural_reference_temp_c"] = round(t_rural, 3)
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f"\nStatistics saved to: {stats_path}")
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
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nTemporal analysis saved to: {output_path}")
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
    analyze_parser.add_argument("--output", help="Output GeoTIFF path")
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
    temporal_parser.set_defaults(func=cmd_temporal)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
