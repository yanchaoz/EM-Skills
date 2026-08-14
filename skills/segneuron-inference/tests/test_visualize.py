import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "segneuron_visualize.py"
SPEC = importlib.util.spec_from_file_location("segneuron_visualize", SCRIPT)
visualize = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(visualize)


class VisualizeTests(unittest.TestCase):
    def test_overlay_is_deterministic_and_marks_boundaries(self):
        raw = np.arange(64, dtype=np.float32).reshape(8, 8)
        labels = np.zeros((8, 8), dtype=np.uint32)
        labels[1:4, 1:4] = 1
        labels[4:7, 4:7] = 2
        first = visualize.instance_overlay(raw, labels)
        second = visualize.instance_overlay(raw, labels)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(first.shape, (8, 8, 3))
        self.assertTrue(np.all(first[4, 4] == 1.0))

    def test_summary_exports_png_svg_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = np.arange(3 * 12 * 12, dtype=np.float32).reshape(3, 12, 12)
            affinities = np.stack([raw / raw.max(), raw[::-1] / raw.max(), np.ones_like(raw) * 0.5])
            membrane = affinities.min(axis=0)
            labels = np.zeros(raw.shape, dtype=np.uint32)
            labels[:, 2:7, 2:7] = 1
            labels[:, 7:10, 7:10] = 2
            for name, array in (("raw", raw), ("aff", affinities), ("mem", membrane), ("inst", labels)):
                np.save(root / f"{name}.npy", array)
            args = visualize.parser().parse_args([
                "summary", "--raw", str(root / "raw.npy"), "--affinities", str(root / "aff.npy"),
                "--membrane", str(root / "mem.npy"), "--instances", str(root / "inst.npy"),
                "--resolution-nm-zyx", "50", "8", "8", "--output-stem", str(root / "summary"),
            ])
            written = visualize.draw_summary(args)
            self.assertEqual({path.suffix for path in written}, {".png", ".svg", ".pdf"})
            self.assertTrue(all(path.stat().st_size > 0 for path in written))


if __name__ == "__main__":
    unittest.main()
