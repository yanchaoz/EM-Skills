import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "cloudvolume_mesh.py"
SPEC = importlib.util.spec_from_file_location("cloudvolume_mesh", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class MeshPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, source):
        cfg = {
            "output_root": "out",
            "mesh_render": {
                "width": 320, "height": 240, "fps": 4, "seconds": 1,
                "max_render_faces": 10000, "png_frames": False,
            },
            "mesh_scenes": [{"id": "fixture", "source": source}],
        }
        path = self.root / "project.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path, cfg

    def test_file_mesh_render_and_verify(self):
        vertices = np.array([
            [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
            [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
        ], dtype=float)
        faces = np.array([
            [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
            [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7],
        ], dtype=int)
        np.savez(self.root / "cube.npz", vertices=vertices, faces=faces)
        path, cfg = self.write_config({"type": "file", "path": "cube.npz"})
        scene = cfg["mesh_scenes"][0]
        audit = MOD.audit_scene(cfg, scene, path)
        self.assertEqual(audit["metrics"]["face_count"], 12)
        MOD.storyboard_scene(cfg, scene, path)
        manifest = MOD.render_scene(cfg, scene, path)
        self.assertEqual(manifest["frame_count"], 4)
        verified = MOD.verify_scene(cfg, scene, path)
        self.assertTrue(verified["ok"])

    def test_bounded_label_roi_to_physical_mesh(self):
        labels = np.zeros((12, 20, 24), dtype=np.uint16)
        labels[3:9, 5:15, 7:19] = 42
        np.save(self.root / "labels.npy", labels)
        path, cfg = self.write_config({
            "type": "labels", "path": "labels.npy", "axes": "zyx",
            "segment_ids": [42], "roi_zyx": [2, 10, 4, 16, 6, 20],
            "resolution_nm_zyx": [40, 8, 8], "voxel_offset_zyx": [100, 200, 300],
        })
        mesh = MOD.load_mesh(cfg["mesh_scenes"][0], path)
        metrics = MOD.mesh_metrics(mesh)
        self.assertGreater(metrics["vertex_count"], 0)
        self.assertGreater(min(metrics["extent_xyz_nm"]), 0)
        self.assertEqual(mesh.provenance["coordinates"], "nm")

    def test_label_source_requires_bounded_roi(self):
        np.save(self.root / "labels.npy", np.ones((4, 4, 4), dtype=np.uint8))
        path, cfg = self.write_config({
            "type": "labels", "path": "labels.npy", "segment_ids": [1],
            "resolution_nm_zyx": [40, 8, 8],
        })
        with self.assertRaisesRegex(ValueError, "bounded roi_zyx"):
            MOD.load_mesh(cfg["mesh_scenes"][0], path)

    def test_precomputed_mesh_retrieval(self):
        vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 5]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=int)
        item = types.SimpleNamespace(vertices=vertices, faces=faces)

        class FakeCloudVolume:
            resolution = np.array([8, 8, 40])
            voxel_offset = np.array([0, 0, 0])

            def __init__(self, uri, mip, progress, fill_missing):
                self.mesh = types.SimpleNamespace(get=lambda ids, fuse: {42: item})

        fake_module = types.ModuleType("cloudvolume")
        fake_module.CloudVolume = FakeCloudVolume
        original = sys.modules.get("cloudvolume")
        sys.modules["cloudvolume"] = fake_module
        try:
            mesh = MOD._load_precomputed({
                "type": "precomputed", "uri": "precomputed:///fixture",
                "segment_ids": [42], "mip": 0, "coordinates": "nm",
            })
        finally:
            if original is None:
                del sys.modules["cloudvolume"]
            else:
                sys.modules["cloudvolume"] = original
        self.assertEqual(len(mesh.vertices), 3)
        self.assertEqual(mesh.provenance["segment_ids"], [42])
        self.assertEqual(mesh.provenance["coordinates"], "nm")

    def test_render_face_limit_fails_closed(self):
        mesh = MOD._as_mesh(
            np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float),
            np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=int),
            {"type": "fixture"},
        )
        with self.assertRaisesRegex(ValueError, "provide a display LOD"):
            MOD.render_frame(mesh, {"width": 320, "height": 240, "max_render_faces": 2}, 0)


if __name__ == "__main__":
    unittest.main()
