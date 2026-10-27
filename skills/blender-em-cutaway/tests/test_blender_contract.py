"""Fast, Blender-independent tests of renderer coordinate and input contracts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_blender.py"
spec = importlib.util.spec_from_file_location("render_blender", SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class BlenderContractTests(unittest.TestCase):
    def test_requires_explicit_finite_camera(self):
        cfg = {"mesh": {"path": "contour.obj", "units": "nm"}}
        with self.assertRaisesRegex(ValueError, "camera.location_mm"):
            renderer.validate_render_config(cfg)
        cfg["camera"] = {"location_mm": [0, 0, 1], "rotation_euler_rad": [0, 0, 0], "ortho_scale_mm": 1}
        renderer.validate_render_config(cfg)
        cfg["contour"]["alpha_center"] = float("nan")
        with self.assertRaisesRegex(ValueError, "alpha_center"):
            renderer.validate_render_config(cfg)

    def test_shader_analytic_boundary_policy(self):
        def m(op, a, b):
            return {"ADD": lambda: a + b, "SUBTRACT": lambda: a - b,
                    "MULTIPLY": lambda: a * b, "MAXIMUM": lambda: max(a, b),
                    "LESS_THAN": lambda: float(a < b), "GREATER_THAN": lambda: float(a > b)}[op]()
        geom = {"outer_uv_bounds_um": [[0, 0], [10, 10]], "display_z_bounds_um": [0, 10],
                "keep_planes": [{"coeff_uvz": [1, 0, 0], "threshold_um": 2, "only_below_v_um": 5}],
                "remove_regions": [{"planes": [{"coeff_uvz": [1, 0, 0], "threshold_um": 6},
                                                 {"coeff_uvz": [0, 0, 1], "threshold_um": 5}]}]}
        self.assertEqual(renderer.clip_mask(geom, [2, 4, 5], m), 1)
        self.assertEqual(renderer.clip_mask(geom, [1, 5, 5], m), 1)
        self.assertEqual(renderer.clip_mask(geom, [1, 4, 5], m), 0)
        self.assertEqual(renderer.clip_mask(geom, [6, 4, 6], m), 1)
        self.assertEqual(renderer.clip_mask(geom, [7, 4, 6], m), 0)
        self.assertEqual(renderer.clip_mask(geom, [10, 10, 0], m), 1)
        self.assertEqual(renderer.clip_mask({}, [1, 2, 3], m), 1)

    def test_reflection_with_nonzero_offset_and_anisotropy(self):
        source = {"voxel_size_nm_xyz": [200, 400, 800], "offset_nm_xyz": [500, -200, 3000]}
        transform = renderer.native_transform(source, [5, 8, 10], True)
        self.assertEqual(transform["reflection_pivot_nm"], 9200)
        self.assertEqual(transform["volume_scale_xyz"], [.0002, .0004, -.0008])
        self.assertEqual(transform["volume_location_mm"], [.0005, -.0002, .0062])
        self.assertAlmostEqual(transform["volume_location_mm"][2] + 4 * transform["volume_scale_xyz"][2], .003)

    def test_obj_negative_indices_reflection_and_no_stretch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mesh.obj"
            path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3/1 -2/2 -1/3\n")
            vertices, faces, digest = renderer.read_obj(path, "um", [100, 200, 300], True, 2000)
            self.assertEqual(faces, [[2, 1, 0]])
            self.assertAlmostEqual(vertices[0][2], .0017)
            self.assertAlmostEqual(vertices[1][0] - vertices[0][0], .001)
            self.assertEqual(len(digest), 64)

    def test_output_refuses_nonempty_without_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "out"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("original")
            with self.assertRaises(FileExistsError):
                renderer.reserve_output(output, False)
            self.assertEqual(renderer.reserve_output(output, True), output.resolve())
            self.assertEqual(sentinel.read_text(), "original")

    def test_output_does_not_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "render.png"
            source.write_bytes(b"source")
            with self.assertRaises(ValueError):
                renderer.reserve_output(folder, True, [source])

    def test_cache_hash_and_coordinate_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, mesh, cache = [root / name for name in ("source.npy", "mesh.obj", "volume.vdb")]
            for path in (source, mesh, cache):
                path.write_bytes(path.name.encode())
            source_cfg = {"path": str(source), "axis_order": "zyx", "voxel_size_nm_xyz": [1, 2, 3],
                          "offset_nm_xyz": [0, 0, 0], "zero_is_missing": True}
            cfg = {"source": source_cfg, "mesh": {"path": str(mesh)}, "display": {"normalization": {"mode": "none"}}}
            manifest = {"schema_version": 1, "source": {**source_cfg, "sha256": renderer.sha256(source),
                        "dtype": "uint8", "shape_zyx": [4, 5, 6]},
                        "mesh": {"sha256": renderer.sha256(mesh)}, "display": cfg["display"],
                        "verification": {"status": "passed", "source_data_modified": False},
                        "vdb": {"sha256": renderer.sha256(cache), "grids": ["em_linear", "em_support"],
                                "transform": "native_index_unit_voxel", "grid_voxel_size": [1, 1, 1], "geometry_pruned": False}}
            (root / "manifest.json").write_text(json.dumps(manifest))
            renderer.validate_cache(cfg, cache)
            cfg["display"]["linear_white_mix"] = .1
            renderer.validate_cache(cfg, cache)  # renderer-only tone change is allowed
            cfg["source"]["offset_nm_xyz"] = [1, 0, 0]
            with self.assertRaisesRegex(ValueError, "offset_nm_xyz"):
                renderer.validate_cache(cfg, cache)
            cfg["source"]["offset_nm_xyz"] = [0, 0, 0]
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "source changed"):
                renderer.validate_cache(cfg, cache)

    def test_world_space_volume_sampling_is_explicit(self):
        # Regression for Blender's default OBJECT-space density and step scaling.
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('volume_data.render.space = "WORLD"', source)


if __name__ == "__main__":
    unittest.main()
