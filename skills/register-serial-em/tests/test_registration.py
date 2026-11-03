"""Synthetic contract/IO tests; these do not execute registration algorithms."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from registration_common import load_project, iter_result, pixel_hash, write_json
from registration_workflow import audit, make_plan, run
from export_aligned import export, xy_downsample
from compare_alignment import compare, bilinear_jacobian_stats


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.array = np.arange(64, dtype=np.uint8).reshape(8, 8)
        self.groups = []
        for group in ("volume-a", "volume-b"):
            sections = []
            for z, name in enumerate(("layer1", "layer10", "layer2")):
                p = self.root / group / (name + ".npy")
                p.parent.mkdir(exist_ok=True)
                np.save(p, self.array + z)
                sections.append({"id": name, "z_index": z, "path": str(p)})
            self.groups.append({"id": group, "sections": sections})
        self.project = self.root / "project.json"
        self.cfg = {"schema_version": 1, "axes": "yx", "voxel_size_nm_xyz": [5, 5, 100],
                    "group_relationship": "independent", "output_root": "derived",
                    "groups": self.groups, "backends": {}}
        self.save_project()

    def tearDown(self):
        self.temp.cleanup()

    def save_project(self):
        write_json(self.project, self.cfg)

    def result(self, name="result", dtype="uint8", offset=(-4, 0, 7)):
        folder = self.root / name
        folder.mkdir()
        sections = []
        for z in range(3):
            a = self.array.astype(dtype) + z
            np.save(folder / f"{z}.npy", a)
            np.save(folder / f"mask{z}.npy", np.ones(a.shape, dtype=np.uint8))
            sections.append({"id": f"s{z}", "z_index": z, "path": f"{z}.npy",
                             "valid_mask": f"mask{z}.npy", "sha256_pixels": pixel_hash(a)})
        cfg = {"schema_version": 1, "artifact_kind": "aligned_intensity", "axes": "zyx",
               "shape_zyx": [3, 8, 8], "dtype": dtype, "voxel_size_nm_xyz": [5, 5, 100],
               "voxel_offset_xyz": list(offset), "sections": sections}
        p = folder / "result.json"
        write_json(p, cfg)
        return p, cfg

    def test_explicit_order_and_independent_groups(self):
        info = audit(self.project)
        self.assertEqual(len(info["groups"]), 2)
        self.assertEqual(info["groups"][0]["shape_zyx"], [3, 8, 8])
        self.assertEqual([s["id"] for s in info["groups"][0]["sections"]], ["layer1", "layer10", "layer2"])
        a = make_plan(self.project, "sofima", "volume-a", "pilot")
        b = make_plan(self.project, "sofima", "volume-b", "pilot")
        self.assertNotEqual(a["run_dir"], b["run_dir"])
        self.assertFalse(Path(a["run_dir"]).exists())
        self.assertEqual(a["status"], "needs_configuration")

    def test_ambiguous_groups_and_missing_sections_rejected(self):
        self.cfg["group_relationship"] = "unknown"
        self.save_project()
        with self.assertRaises(ValueError):
            load_project(self.project)
        self.cfg["group_relationship"] = "independent"
        self.cfg["groups"][0]["sections"][1]["z_index"] = 5
        self.save_project()
        with self.assertRaises(ValueError):
            load_project(self.project)

    def test_source_overlap_rejected(self):
        self.cfg["output_root"] = str(self.root)
        self.save_project()
        with self.assertRaises(ValueError):
            load_project(self.project)

    def test_seamless_requires_model_and_physical_scale(self):
        self.cfg["backends"]["metroem-corgie"] = {
            "repositories": [{"name": n, "path": "/code/" + n, "commit": "1" * 40} for n in ("metroem", "corgie")],
            "stages": {"pilot": [{"argv": ["corgie", "--help"], "expected_outputs": ["{run_dir}/native"]}]}}
        self.save_project()
        plan = make_plan(self.project, "metroem-corgie", "volume-a", "pilot")
        self.assertEqual(plan["status"], "needs_configuration")
        self.assertTrue(any("checkpoint" in s for s in plan["unresolved"]))

    def test_json_argv_preserved_and_output_isolation(self):
        spec = '{"ApplyModel":{"params":{"path":"/models/a"}}}'
        self.cfg["backends"]["sofima"] = {"stages": {"pilot": [{
            "argv": ["python", "-c", "pass", spec], "expected_outputs": ["{run_dir}/out.json"]}]}}
        self.save_project()
        plan = make_plan(self.project, "sofima", "volume-a", "pilot")
        self.assertEqual(plan["commands"][0]["argv"][-1], spec)
        self.cfg["backends"]["sofima"]["stages"]["pilot"][0]["expected_outputs"] = ["../other/out"]
        self.save_project()
        with self.assertRaises(ValueError):
            make_plan(self.project, "sofima", "volume-a", "pilot")

    @unittest.skipUnless(shutil.which("git"), "git required for native-harness test")
    def test_execution_resume_and_changed_config_guard(self):
        repo = self.root / "upstream"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        driver = repo / "driver.py"
        driver.write_text("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('native fixture')\n")
        subprocess.run(["git", "-C", str(repo), "add", "driver.py"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
        sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        self.cfg["backends"]["sofima"] = {"python": sys.executable,
            "repositories": [{"name": "sofima", "path": str(repo), "commit": sha}],
            "stages": {"pilot": [{"argv": ["{python}", str(driver), "{run_dir}/native.txt"],
                                 "expected_outputs": ["{run_dir}/native.txt"]}]}}
        self.save_project()
        record = run(self.project, "sofima", "volume-a", "pilot")
        self.assertEqual(record["status"], "native_commands_completed")
        self.assertEqual(run(self.project, "sofima", "volume-a", "pilot")["identity"], record["identity"])
        self.cfg["voxel_size_nm_xyz"][2] = 101
        self.save_project()
        with self.assertRaisesRegex(ValueError, "changed"):
            run(self.project, "sofima", "volume-a", "pilot")

    def test_pixel_hash_detects_changed_aligned_data(self):
        p, cfg = self.result()
        np.save(p.parent / "1.npy", self.array)
        with self.assertRaisesRegex(ValueError, "pixels changed"):
            list(iter_result(p))

    def test_xy_average_and_odd_grid_guard(self):
        a = np.array([[0, 1], [1, 0]], dtype=np.uint8)
        np.testing.assert_array_equal(xy_downsample(a), [[1]])
        with self.assertRaises(ValueError):
            xy_downsample(np.ones((5, 4)))
        p, cfg = self.result(offset=(-3, 0, 7))
        with self.assertRaisesRegex(ValueError, "coarsest grid"):
            export(p, self.root / "odd", cloudvolume=True, mips=3)
        self.assertFalse((self.root / "odd").exists())

    @unittest.skipUnless(importlib.util.find_spec("tifffile"), "tifffile required")
    def test_tiff_lossless_types_and_metadata(self):
        import tifffile
        for dtype in ("uint8", "uint16", "float32"):
            with self.subTest(dtype=dtype):
                p, cfg = self.result(dtype, dtype)
                out = self.root / ("tiff-" + dtype)
                report = export(p, out, tiff=True)
                self.assertEqual(report["full_planes_verified"], 3)
                with tifffile.TiffFile(out / "tiff" / "layer000002.tif") as tif:
                    np.testing.assert_array_equal(tif.asarray(), self.array.astype(dtype) + 1)
                    meta = json.loads(tif.pages[0].description)
                    self.assertEqual(meta["voxel_offset_xyz"], [-4, 0, 7])
                    self.assertEqual(meta["z_position_nm"], 800)
                with self.assertRaises(ValueError):
                    export(p, out, tiff=True)

    @unittest.skipUnless(importlib.util.find_spec("cloudvolume") and importlib.util.find_spec("tifffile"), "cloud-volume/tifffile required")
    def test_precomputed_xy_only_negative_offset_and_tiff_roundtrip(self):
        from cloudvolume import CloudVolume
        for dtype in ("uint8", "uint16", "float32"):
            with self.subTest(dtype=dtype):
                p, cfg = self.result("cv-source-" + dtype, dtype)
                out = self.root / ("cv-" + dtype)
                report = export(p, out, cloudvolume=True, mips=3)
                self.assertEqual(report["mips_verified"], 3)
                url = "file://" + str(out / "image")
                info = CloudVolume(url, progress=False).info
                for m, scale in enumerate(info["scales"]):
                    self.assertEqual(scale["size"], [8 // 2**m, 8 // 2**m, 3])
                    self.assertEqual(scale["resolution"], [5 * 2**m, 5 * 2**m, 100])
                    self.assertEqual(scale["voxel_offset"], [-4 // 2**m, 0, 7])
                    self.assertEqual(scale["encoding"], "raw")
                cfg["cloudvolume"] = url
                for s in cfg["sections"]:
                    del s["path"]
                q = self.root / (dtype + "-cv-result.json")
                write_json(q, cfg)
                report = export(q, self.root / (dtype + "-from-cv"), tiff=True)
                self.assertEqual(report["full_planes_verified"], 3)

    def test_common_support_and_null_correlation(self):
        a, _ = self.result("baseline")
        b, cfg = self.result("candidate")
        mask = np.zeros((8, 8), dtype=bool)
        mask[:, :4] = 1
        for z in range(3):
            np.save(b.parent / f"mask{z}.npy", mask)
        report = compare([a, b])
        self.assertEqual(report["pairs"][0]["common_pixels"], 32)
        self.assertEqual(report["pairs"][0]["ncc"], [1.0, 1.0])
        for s in cfg["sections"]:
            np.save(b.parent / s["path"], np.zeros((8, 8), dtype=np.uint8))
            s.pop("sha256_pixels")
        write_json(b, cfg)
        report = compare([a, b])
        self.assertIsNone(report["pairs"][0]["ncc"][1])
        cfg["voxel_offset_xyz"][0] += 1
        write_json(b, cfg)
        with self.assertRaisesRegex(ValueError, "physical grid"):
            compare([a, b])

    def test_explicit_masks_required(self):
        a, _ = self.result("baseline")
        b, cfg = self.result("candidate")
        cfg["sections"][0].pop("valid_mask")
        write_json(b, cfg)
        with self.assertRaisesRegex(ValueError, "valid_mask"):
            compare([a, b])

    def test_known_translation_and_fold_geometry(self):
        d = np.zeros((2, 4, 5))
        d[0] = 12
        d[1] = -7
        self.assertEqual(bilinear_jacobian_stats(d)["minimum_corner_jacobian"], 1.0)
        d[0] = -2 * np.arange(5)[None, :]
        self.assertEqual(bilinear_jacobian_stats(d)["nonpositive_cells"], 12)
        d[0, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            bilinear_jacobian_stats(d)


if __name__ == "__main__":
    unittest.main()
