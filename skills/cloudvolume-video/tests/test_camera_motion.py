import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "cloudvolume_video.py"
SPEC = importlib.util.spec_from_file_location("cloudvolume_video", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class CameraMotionTest(unittest.TestCase):
    def setUp(self):
        self.stops = [(100_000.0, 200_000.0), (500_000.0, 350_000.0)]
        self.fov = 200_000.0
        self.camera = dict(MOD.DEFAULT_CAMERA)

    def pose(self, t, include_overview=False):
        return MOD.camera_pose(t, self.stops, self.fov, 4.0, 3.0, 2.0,
                               include_overview, self.camera)

    def test_easing_endpoints_and_monotonicity(self):
        for name in ("linear", "smoothstep", "smootherstep", "cosine"):
            values = [MOD.easing_value(name, x / 20) for x in range(21)]
            self.assertEqual(values[0], 0.0)
            self.assertEqual(values[-1], 1.0)
            self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))

    def test_hold_to_move_is_continuous(self):
        hold_end = self.pose(3.0 - 1e-7)
        move_start = self.pose(3.0)
        self.assertLess(abs(hold_end["center"][0] - move_start["center"][0]), 0.1)
        self.assertLess(abs(hold_end["center"][1] - move_start["center"][1]), 0.1)
        self.assertLess(abs(hold_end["fov_nm"] - move_start["fov_nm"]), 0.1)

    def test_default_review_holds_are_pixel_stable_poses(self):
        first = self.pose(0.0)
        middle = self.pose(1.5)
        last = self.pose(3.0 - 1e-7)
        self.assertEqual(first["phase"], "hold")
        self.assertEqual(first["center"], middle["center"])
        self.assertEqual(middle["center"], last["center"])
        self.assertEqual(first["fov_nm"], middle["fov_nm"])
        self.assertEqual(middle["fov_nm"], last["fov_nm"])

    def test_hold_motion_remains_available_only_when_explicitly_configured(self):
        camera = dict(self.camera, hold_pan_fraction=0.03, hold_zoom_fraction=0.05)
        first = MOD.camera_pose(0.0, self.stops, self.fov, 4.0, 3.0, 2.0,
                                False, camera)
        last = MOD.camera_pose(3.0 - 1e-7, self.stops, self.fov, 4.0, 3.0, 2.0,
                               False, camera)
        self.assertNotEqual(first["center"], last["center"])
        self.assertGreater(first["fov_nm"], last["fov_nm"])

    def test_move_midpoint_zooms_out_and_remains_between_stops(self):
        start = self.pose(3.0)
        middle = self.pose(4.0)
        end = self.pose(5.0 - 1e-7)
        self.assertEqual(middle["phase"], "move")
        self.assertGreater(middle["fov_nm"], max(start["fov_nm"], end["fov_nm"]))
        self.assertGreater(middle["center"][0], min(start["center"][0], end["center"][0]))
        self.assertLess(middle["center"][0], max(start["center"][0], end["center"][0]))

    def test_entry_zoom_reaches_first_hold_without_jump(self):
        entry_start = self.pose(0.0, include_overview=True)
        entry_end = self.pose(4.0 - 1e-7, include_overview=True)
        hold_start = self.pose(4.0, include_overview=True)
        self.assertEqual(entry_start["phase"], "entry_zoom")
        self.assertAlmostEqual(entry_start["fov_nm"], self.fov * 1.4)
        self.assertLess(abs(entry_end["fov_nm"] - hold_start["fov_nm"]), 0.1)
        self.assertLess(abs(entry_end["center"][0] - hold_start["center"][0]), 0.1)

    def test_entry_moves_from_context_center_to_first_random_stop(self):
        context = (900_000.0, 800_000.0)
        start = MOD.camera_pose(0.0, self.stops, self.fov, 4.0, 3.0, 2.0,
                                True, self.camera, context)
        middle = MOD.camera_pose(2.0, self.stops, self.fov, 4.0, 3.0, 2.0,
                                 True, self.camera, context)
        end = MOD.camera_pose(4.0 - 1e-7, self.stops, self.fov, 4.0, 3.0, 2.0,
                              True, self.camera, context)
        hold = MOD.camera_pose(4.0, self.stops, self.fov, 4.0, 3.0, 2.0,
                               True, self.camera, context)
        self.assertEqual(start["center"], context)
        self.assertTrue(self.stops[0][0] < middle["center"][0] < context[0])
        self.assertLess(abs(end["center"][0] - hold["center"][0]), 0.1)

    def test_invalid_camera_range_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = {
                "project_name": "fixture", "source_root": str(root / "source"),
                "output_root": str(root / "output"),
                "video": {"camera": {"hold_pan_fraction": 0.9}},
                "specimens": [{
                    "id": "fixture", "raw": "raw", "layers": [{
                        "id": "mask", "dataset": "mask", "color_rgb": [1, 2, 3],
                        "opacity": 0.5,
                    }],
                }],
            }
            path = root / "project.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hold_pan_fraction"):
                MOD.load_config(path)

    def test_seeded_random_stops_are_reproducible_and_bounded(self):
        pipeline = MOD.Pipeline.__new__(MOD.Pipeline)
        pipeline.cv2, pipeline.np = cv2, np
        pipeline.W, pipeline.H = 1920, 1080
        pipeline.v = {"detail_fov_um": 200.0}
        raw = np.tile(np.arange(100, dtype=np.uint8), (100, 1))
        tissue = np.ones((100, 100), dtype=bool)
        meta = {
            "physical_size_nm": [1_000_000, 1_000_000],
            "preview_resolution_nm": 10_000,
            "preview_bounds_nm_relative_xyxy": [875_000, 1_875_000, 1_660_000, 2_660_000],
        }
        specimen = {"id": "fixture", "story": {"local_stops": {
            "mode": "seeded_random", "seed": 20260815, "count": 4,
            "min_tissue_fraction": 0.7, "min_center_distance_um": 150,
        }}}
        first = pipeline.choose_stops(raw, tissue, meta, specimen)
        second = pipeline.choose_stops(raw, tissue, meta, specimen)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        for x, y in first:
            self.assertTrue(975_000 <= x <= 1_775_000)
            self.assertTrue(1_716_250 <= y <= 2_603_750)
        self.assertTrue(all(np.hypot(a[0] - b[0], a[1] - b[1]) >= 150_000
                            for index, a in enumerate(first) for b in first[index + 1:]))


if __name__ == "__main__":
    unittest.main()
