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


if __name__ == "__main__":
    unittest.main()
