import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "gallery", ROOT / "scripts" / "visualize_subvolume_gallery.py"
)
gallery = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gallery)


class GalleryTests(unittest.TestCase):
    def test_render(self):
        try:
            import matplotlib  # noqa: F401
            import tifffile
        except ImportError:
            self.skipTest("visualization dependencies unavailable")
        selection = {
            "project_id": "synthetic",
            "source": {"voxel_size_nm_zyx": [30, 6, 6]},
            "selected_subvolumes": [{
                "rank": 1,
                "bbox_zyx": [[0, 0, 0], [2, 16, 16]],
                "derived_shape_zyx": [2, 16, 16],
                "newly_covered_patch_count": 4,
                "cumulative_coverage_rate": 0.5,
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            raw = td / "raw.tif"
            spec = td / "selection.json"
            out = td / "gallery.png"
            tifffile.imwrite(raw, np.arange(2 * 16 * 16, dtype=np.uint16).reshape(2, 16, 16))
            spec.write_text(json.dumps(selection), encoding="utf-8")
            gallery.render(raw, spec, out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
