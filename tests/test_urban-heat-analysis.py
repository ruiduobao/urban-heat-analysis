#!/usr/bin/env python3
"""Tests for urban-heat-analysis: UHI calculation."""

import sys
import os
import json
import tempfile
import unittest
import importlib.util

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "urban-heat-analysis.py")
spec = importlib.util.spec_from_file_location("urban_heat_analysis", SCRIPT_PATH)
uha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uha)


class TestUHIClassification(unittest.TestCase):
    """Test UHI classification logic."""

    def test_strong_uhi(self):
        import numpy as np
        data = np.array([[5.0, 3.0], [1.0, -1.0]])
        classified = uha.classify_uhi(data)
        self.assertEqual(classified[0, 0], 3)  # Strong
        self.assertEqual(classified[0, 1], 2)  # Moderate
        self.assertEqual(classified[1, 0], 1)  # Weak
        self.assertEqual(classified[1, 1], 0)  # None/Cool

    def test_boundary_values(self):
        import numpy as np
        data = np.array([[0.0, 2.0, 4.0]])
        classified = uha.classify_uhi(data)
        self.assertEqual(classified[0, 0], 1)  # 0°C -> Weak
        self.assertEqual(classified[0, 1], 2)  # 2°C -> Moderate
        self.assertEqual(classified[0, 2], 3)  # 4°C -> Strong

    def test_nodata_handling(self):
        import numpy as np
        data = np.array([[np.nan, 3.0]])
        classified = uha.classify_uhi(data)
        self.assertEqual(classified[0, 0], 255)
        self.assertEqual(classified[0, 1], 2)


class TestLSTConversion(unittest.TestCase):
    """Test LST Kelvin to Celsius conversion."""

    def test_modis_lst_conversion(self):
        import numpy as np
        raw = np.array([[15000]])
        celsius = uha.lst_to_celsius(raw)
        expected = 15000 * 0.02 - 273.15
        self.assertAlmostEqual(celsius[0, 0], expected, places=2)

    def test_zero_value(self):
        import numpy as np
        raw = np.array([[0]])
        celsius = uha.lst_to_celsius(raw)
        self.assertAlmostEqual(celsius[0, 0], -273.15, places=2)


class TestUHIComputation(unittest.TestCase):
    """Test UHI intensity computation."""

    def test_compute_uhi_auto_rural(self):
        import numpy as np
        lst = np.array([
            [30.0, 31.0, 29.0],
            [25.0, 24.0, 26.0],
            [25.0, 25.0, 25.0],
        ])
        uhi, t_rural = uha.compute_uhi(lst, rural_fraction=0.3)
        self.assertLess(t_rural, 26.0)
        self.assertGreater(uhi[0, 0], 0)

    def test_compute_uhi_with_mask(self):
        import numpy as np
        lst = np.array([
            [30.0, 31.0],
            [25.0, 24.0],
        ])
        rural_mask = np.array([
            [False, False],
            [True, True],
        ])
        uhi, t_rural = uha.compute_uhi(lst, rural_mask=rural_mask)
        self.assertAlmostEqual(t_rural, 24.5)
        self.assertAlmostEqual(uhi[0, 0], 5.5)
        self.assertAlmostEqual(uhi[0, 1], 6.5)


class TestStatistics(unittest.TestCase):
    """Test UHI statistics computation."""

    def test_compute_statistics(self):
        import numpy as np
        uhi = np.array([[1.0, 2.0, 3.0], [4.5, -1.0, 0.5]])
        classified = uha.classify_uhi(uhi)
        stats = uha.compute_statistics(uhi, classified)

        self.assertIn("uhi_intensity", stats)
        self.assertIn("classification_percentages", stats)
        self.assertAlmostEqual(stats["uhi_intensity"]["mean"], np.nanmean(uhi), places=2)
        self.assertAlmostEqual(stats["uhi_intensity"]["max"], np.nanmax(uhi), places=2)


class TestFormat(unittest.TestCase):
    """Tests for --format (csv / json) flag on analyze/temporal/from-place."""

    def test_analyze_subcommand_help_shows_format(self):
        """`analyze --help` should mention the new --format flag."""
        import subprocess
        import sys as _sys
        result = subprocess.run(
            [_sys.executable, SCRIPT_PATH, "analyze", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--format", result.stdout)
        self.assertIn("csv", result.stdout)
        self.assertIn("json", result.stdout)

    def test_temporal_subcommand_help_shows_format(self):
        """`temporal --help` should mention the new --format flag."""
        import subprocess
        import sys as _sys
        result = subprocess.run(
            [_sys.executable, SCRIPT_PATH, "temporal", "--help"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--format", result.stdout)
        self.assertIn("csv", result.stdout)
        self.assertIn("json", result.stdout)

    def test_temporal_format_csv(self):
        """`temporal --format csv` should produce CSV with seasonal rows."""
        import numpy as np
        # Build a small fake LST geotiff in a temp dir.
        # MODIS LST raw values: 0.02 * raw - 273.15 = Celsius.
        # So 25 °C -> raw = (25 + 273.15) / 0.02 = 14908
        tmp = tempfile.mkdtemp()
        lst_path = os.path.join(tmp, "lst.tif")
        arr = np.full((10, 10), 14908.0, dtype=np.float32)  # ~25 °C
        arr[2:5, 2:5] = 15108.0  # ~29 °C urban hotspot
        with uha.rasterio.open(
            lst_path, "w",
            driver="GTiff", height=10, width=10, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=uha.rasterio.transform.from_bounds(0, 0, 1, 1, 10, 10),
        ) as dst:
            dst.write(arr, 1)
        out_csv = os.path.join(tmp, "temporal.csv")
        args = uha.argparse.Namespace(
            lst_dir=tmp, rural_mask=None, output=out_csv,
            fmt="csv", json=False,
        )
        uha.cmd_temporal(args)
        self.assertTrue(os.path.exists(out_csv))
        with open(out_csv, "r", encoding="utf-8") as f:
            text = f.read()
        # CSV should have season column
        self.assertIn("season", text)

    def test_temporal_format_json(self):
        """`temporal --format json` should produce JSON array (default behavior)."""
        import numpy as np
        tmp = tempfile.mkdtemp()
        lst_path = os.path.join(tmp, "lst.tif")
        arr = np.full((10, 10), 14908.0, dtype=np.float32)  # ~25 °C
        arr[2:5, 2:5] = 15108.0  # ~29 °C urban hotspot
        with uha.rasterio.open(
            lst_path, "w",
            driver="GTiff", height=10, width=10, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=uha.rasterio.transform.from_bounds(0, 0, 1, 1, 10, 10),
        ) as dst:
            dst.write(arr, 1)
        out_json = os.path.join(tmp, "temporal.json")
        args = uha.argparse.Namespace(
            lst_dir=tmp, rural_mask=None, output=out_json,
            fmt="json", json=False,
        )
        uha.cmd_temporal(args)
        self.assertTrue(os.path.exists(out_json))
        with open(out_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_temporal_format_inferred_from_suffix(self):
        """When --format not given and output ends with .csv, write CSV."""
        import numpy as np
        tmp = tempfile.mkdtemp()
        lst_path = os.path.join(tmp, "lst.tif")
        arr = np.full((10, 10), 14908.0, dtype=np.float32)  # ~25 °C
        arr[2:5, 2:5] = 15108.0  # ~29 °C urban hotspot
        with uha.rasterio.open(
            lst_path, "w",
            driver="GTiff", height=10, width=10, count=1,
            dtype="float32", crs="EPSG:4326",
            transform=uha.rasterio.transform.from_bounds(0, 0, 1, 1, 10, 10),
        ) as dst:
            dst.write(arr, 1)
        out_csv = os.path.join(tmp, "inferred.csv")
        args = uha.argparse.Namespace(
            lst_dir=tmp, rural_mask=None, output=out_csv,
            fmt=None, json=False,
        )
        uha.cmd_temporal(args)
        self.assertTrue(os.path.exists(out_csv))
        with open(out_csv, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("season", text)


if __name__ == "__main__":
    unittest.main()
