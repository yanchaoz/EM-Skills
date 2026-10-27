"""Run with python -m unittest discover -s tests (numpy required)."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cutaway_core import (display_layer, keep_mask, load_config, native_world_um,
                          open_source, source_support, transform_metadata, validate_config, world_to_uv)
from audit_cutaway import audit
from make_demo import make_demo
from render_blender import clip_mask, native_transform


def config():
    return dict(schema_version=1,
        source=dict(path="/data/source.npy", axis_order="zyx", voxel_size_nm_xyz=[200, 300, 500],
                    offset_nm_xyz=[1000, 2000, 3000], zero_is_missing=True),
        geometry=dict(reflect_z=True, basis_rotation_deg=0), output_dir="/output")


class CoordinatesTest(unittest.TestCase):
    def test_anisotropic_reflection(self):
        cfg = config()
        xyz = native_world_um(cfg, (4,5,6), 2,3,0)
        np.testing.assert_allclose(xyz, [1.4,2.9,4.5])
        np.testing.assert_allclose(native_world_um(cfg, (4,5,6), 2,3,3), [1.4,2.9,3.0])
        self.assertEqual(transform_metadata(cfg,(4,5,6))["reflection_pivot_nm"], 7500)
        cfg["geometry"]["reflect_z"] = False
        np.testing.assert_allclose(native_world_um(cfg,(4,5,6),2,3,3), [1.4,2.9,4.5])

    def test_uv_basis(self):
        cfg = config()
        cfg["geometry"]["basis_rotation_deg"] = 90
        np.testing.assert_allclose(world_to_uv(cfg,2,3), [3,-2], atol=1e-10)

    def test_renderer_and_auditor_transform_contract(self):
        cfg = config()
        for reflected in (False, True):
            cfg["geometry"]["reflect_z"] = reflected
            actual = native_transform(cfg["source"], (7,13,19), reflected)
            expected = transform_metadata(cfg,(7,13,19))
            self.assertEqual(actual,expected)
            for z in (0,3,6):
                indices = np.array([8,5,z])
                world = (indices*np.array(actual["volume_scale_xyz"])
                         + np.array(actual["volume_location_mm"]))*1000
                np.testing.assert_allclose(world,native_world_um(cfg,(7,13,19),*indices))

    def test_renderer_mask_matches_native_audit(self):
        cfg = config()
        cfg["geometry"].update(outer_uv_bounds_um=[[0,0],[10,10]], display_z_bounds_um=[0,10],
            keep_planes=[dict(coeff_uvz=[1,0,-.25],threshold_um=2,only_below_v_um=8)],
            remove_regions=[dict(planes=[dict(coeff_uvz=[1,0,0],threshold_um=6),
                                        dict(coeff_uvz=[0,0,1],threshold_um=5)])])
        def m(op,a,b):
            return {"ADD":lambda:a+b,"SUBTRACT":lambda:a-b,"MULTIPLY":lambda:a*b,
                    "MAXIMUM":lambda:np.maximum(a,b),"LESS_THAN":lambda:np.asarray(a<b,float),
                    "GREATER_THAN":lambda:np.asarray(a>b,float)}[op]()
        u,v,z = np.meshgrid([-1,0,1,2,3,6,7,10,11],[0,3,8,9,10],[0,4,5,6,10],indexing="ij")
        np.testing.assert_array_equal(keep_mask(cfg,u,v,z),
                                      clip_mask(cfg["geometry"],(u,v,z),m).astype(bool))

    def test_mask_boundary_and_exception(self):
        cfg = config()
        cfg["geometry"].update(outer_uv_bounds_um=[[0,0],[10,10]], display_z_bounds_um=[0,10],
            keep_planes=[dict(coeff_uvz=[1,0,0],threshold_um=2,only_below_v_um=8)],
            remove_regions=[dict(planes=[dict(coeff_uvz=[1,0,0],threshold_um=6),
                                        dict(coeff_uvz=[0,0,1],threshold_um=5)])])
        result = keep_mask(cfg, [1,1,2,6,7,7], [2,9,2,2,2,2], [3,3,3,6,5,6])
        np.testing.assert_array_equal(result, [False,True,True,True,True,False])

    def test_zero_semantics(self):
        cfg = config()
        layer = np.array([[0, 128, 255]], np.uint8)
        values, support, _ = display_layer(cfg,layer)
        np.testing.assert_array_equal(support, [[False,True,True]])
        self.assertEqual(float(values[0,0]),0)
        self.assertAlmostEqual(float(values[0,1]),.2158605, places=6)
        cfg["source"]["zero_is_missing"] = False
        self.assertTrue(source_support(cfg,layer).all())

    def test_validation_and_input_output_separation(self):
        cfg = config()
        validate_config(cfg)
        cfg["source"]["voxel_size_nm_xyz"][2] = -1
        with self.assertRaises(ValueError): validate_config(cfg)
        cfg = config()
        cfg["output_dir"] = "/data"
        with self.assertRaises(ValueError): validate_config(cfg)

    def test_native_uint8_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"bad.npy"
            np.save(path,np.ones((2,3,4),np.uint16))
            cfg = config(); cfg["source"]["path"] = str(path)
            with self.assertRaises(ValueError): open_source(cfg)

    def test_demo_and_geometry_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_demo(tmp)
            cfg = load_config(path)
            raw = open_source(cfg)
            self.assertEqual(raw.shape,(32,72,48))
            self.assertFalse(raw.flags.writeable)
            report = audit(path,slices=[0,15,31])
            self.assertEqual(report["scope"],"selected slices only")
            modified = json.loads(path.read_text())
            modified["geometry"]["remove_regions"][1]["planes"][2]["threshold_um"] = 20
            revised = Path(tmp)/"revised.json"
            revised.write_text(json.dumps(modified))
            result = audit(revised,compare=path)
            self.assertGreater(result["totals"]["added_valid_voxels"],0)
            self.assertEqual(result["totals"]["removed_valid_voxels"],0)
            self.assertEqual(result["changed_raw_z_indices"],[11,12,13,14])
            self.assertTrue(result["frozen_settings_comparison"]["unchanged"])
            with self.assertRaises(ValueError): audit(path,slices=[32])
            del raw  # Release Windows mmap before TemporaryDirectory cleanup.

    def test_audit_reports_non_geometry_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = make_demo(tmp)
            modified = json.loads(baseline.read_text())
            modified["camera"]["location_mm"][0] += .002
            modified["mesh"]["offset_nm_xyz"][2] += 100
            revised = Path(tmp)/"settings-only.json"
            revised.write_text(json.dumps(modified))
            result = audit(revised,compare=baseline)
            self.assertEqual(result["changed_raw_z_indices"],[])
            self.assertEqual(result["totals"]["added_valid_voxels"],0)
            self.assertEqual(result["totals"]["removed_valid_voxels"],0)
            comparison = result["frozen_settings_comparison"]
            self.assertFalse(comparison["unchanged"])
            self.assertEqual(set(comparison["changed_fields"]),
                             {"camera.location_mm[0]", "mesh.offset_nm_xyz[2]"})
            self.assertEqual(comparison["sections"]["mesh"]["baseline"]["offset_nm_xyz"][2],0)
            self.assertEqual(comparison["sections"]["mesh"]["current"]["offset_nm_xyz"][2],100)
            self.assertTrue(comparison["sections"]["display"]["unchanged"])

    def test_uncut_reflection_is_not_mistaken_for_frozen_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = make_demo(tmp)
            cfg = json.loads(baseline.read_text())
            cfg["geometry"] = {"reflect_z":True,"basis_rotation_deg":0}
            baseline.write_text(json.dumps(cfg))
            cfg["geometry"]["reflect_z"] = False
            revised = Path(tmp)/"reflection-only.json"
            revised.write_text(json.dumps(cfg))
            report = audit(revised,compare=baseline)
            self.assertEqual(report["changed_raw_z_indices"],[])
            self.assertEqual(report["totals"]["added_valid_voxels"],0)
            self.assertEqual(report["totals"]["removed_valid_voxels"],0)
            settings = report["frozen_settings_comparison"]
            self.assertFalse(settings["unchanged"])
            self.assertEqual(settings["changed_fields"],["orientation.reflect_z"])
            self.assertEqual(settings["sections"]["orientation"]["baseline"],{"reflect_z":True})
            self.assertEqual(settings["sections"]["orientation"]["current"],{"reflect_z":False})


if __name__ == "__main__":
    unittest.main()
