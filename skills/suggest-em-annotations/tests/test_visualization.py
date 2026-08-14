import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("visualizer", ROOT / "scripts" / "visualize_annotation_advice.py")
visualizer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(visualizer)


class VisualizationTests(unittest.TestCase):
    def test_render(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib unavailable")
        manifest = {
            "patch_count": 4,
            "source": {"shape_zyx": [2, 8, 8]},
        }
        selection = {
            "project_id": "synthetic",
            "covered_patch_ids": [0, 1, 2],
            "selected_patch_ids": [0, 1],
            "coverage_curve": [{"rank": 1, "coverage_rate": 0.75}],
            "selected_subvolumes": [{
                "rank": 1,
                "candidate_id": "sv-0000-0000-0000",
                "bbox_zyx": [[0, 1, 1], [1, 5, 5]],
                "newly_covered_patch_count": 3,
                "review_status": "pending",
            }],
        }
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mp = td / "manifest.json"
            sp = td / "selection.json"
            ep = td / "embedding.npy"
            op = td / "figure.png"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            sp.write_text(json.dumps(selection), encoding="utf-8")
            np.save(ep, np.eye(4, 3, dtype=np.float32))
            visualizer.render(mp, sp, ep, op)
            self.assertTrue(op.exists())
            self.assertGreater(op.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
