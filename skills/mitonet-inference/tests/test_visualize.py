import importlib.util
from pathlib import Path
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mitonet_visualize.py"
SPEC = importlib.util.spec_from_file_location("mitonet_visualize", SCRIPT)
visualize = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(visualize)


class VisualizeTests(unittest.TestCase):
    def test_overlay_and_metrics(self):
        raw = np.arange(4 * 8 * 8, dtype=np.float32).reshape(4, 8, 8)
        labels = np.zeros(raw.shape, np.uint32)
        labels[:, 1:4, 1:4] = 1; labels[1:3, 5:7, 5:7] = 2
        image = visualize.overlay(raw[1], labels[1])
        report = visualize.metrics(labels)
        self.assertEqual(image.shape, (8, 8, 3))
        self.assertEqual(report["object_count"], 2)
        self.assertEqual(report["z_span_slices"]["max"], 4)

    def test_default_display_indices_follow_foreground(self):
        labels = np.zeros((5, 8, 8), dtype=np.uint32)
        labels[4, 6, 2:7] = 1
        self.assertEqual(visualize.select_display_indices(labels, None, None), (4, 6))


if __name__ == "__main__":
    unittest.main()
