import importlib.util
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "adapter", ROOT / "scripts" / "extract_emfoundation_embeddings.py"
)
adapter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(adapter)


class AdapterTests(unittest.TestCase):
    def test_align_end_is_deterministic(self):
        self.assertEqual(adapter.grid_starts(11, 4, 3, "valid"), [0, 3, 6])
        self.assertEqual(adapter.grid_starts(11, 4, 3, "align_end"), [0, 3, 6, 7])

    def test_reference_normalization(self):
        patch = np.arange(32, dtype=np.uint8).reshape(2, 4, 4)
        result = adapter.normalize_patch(patch)
        self.assertEqual(result.dtype, np.float32)
        self.assertAlmostEqual(float(result.mean()), 0.0, places=5)
        self.assertAlmostEqual(float(result.std()), 1.0, places=4)

    def test_rejects_unvalidated_high_dynamic_range(self):
        patch = np.asarray([[[0, 4095]]], dtype=np.uint16)
        with self.assertRaises(ValueError):
            adapter.normalize_patch(patch)


if __name__ == "__main__":
    unittest.main()
