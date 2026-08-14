import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mitonet_pipeline.py"
SPEC = importlib.util.spec_from_file_location("mitonet_pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)

ADAPTER_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mitonet_adapter.py"
ADAPTER_SPEC = importlib.util.spec_from_file_location("mitonet_adapter", ADAPTER_SCRIPT)
adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
assert ADAPTER_SPEC and ADAPTER_SPEC.loader
ADAPTER_SPEC.loader.exec_module(adapter)


def profile(mode="stack"):
    return {
        "mode": mode, "median_kernel": 3, "segmentation_confidence": 0.3,
        "center_confidence": 0.1, "center_min_distance": 3, "merge_iou": 0.25,
        "merge_ioa": 0.25, "pixel_vote": 2, "cluster_iou": 0.75,
        "allow_one_view": False, "fine_boundaries": False, "min_size_vox": 50,
        "min_span_slices": 2, "label_divisor": 20000,
        "downsample_factor": 1,
    }


def base_config(root: Path):
    source = root / "raw.npy"; source.write_bytes(b"source")
    return {
        "project": {"id": "mito-test"},
        "source": {"uri": str(source), "format": "npy", "axis_order": "zyx", "shape_zyx": [8, 64, 64], "resolution_nm_zyx": [40, 8, 8], "offset_vox_zyx": [0, 0, 0], "bbox_vox_zyx": [0, 0, 0, 8, 64, 64], "read_only": True, "identity": "fixture"},
        "model": {"repository": "volume-em/empanada", "repo_path": str(root), "repo_commit": "0" * 40, "variant": "MitoNet_v1_mini", "model_config": str(root / "missing.yaml"), "model_config_sha256": "0" * 64, "checkpoint": str(root / "missing.pth"), "checkpoint_sha256": "0" * 64, "target_resolution_nm_zyx": [40, 16, 16], "z_policy": "preserve"},
        "planning": {"pilot_rois": [[0, 0, 0, 8, 64, 64]], "max_end_error_nm": 8},
        "inference": {"profiles": {"sensitive": profile(), "balanced": profile()}, "orthoplane_reviewed": False},
        "commands": {
            "prepare": {"argv": ["tool", "{config_path}"], "cwd": "{skill_path}", "env": {}, "expected_outputs": ["raw-model-grid.tif"]},
            "profile": {"argv": ["tool", "--profile", "{profile}", "--thr", "{profile_segmentation_confidence}"], "cwd": "{skill_path}", "env": {}, "expected_outputs": ["profiles/{profile}.tif"]},
            "infer": {"argv": ["tool", "--profile", "{selected_profile}", "--factor", "{profile_downsample_factor}"], "cwd": "{skill_path}", "env": {}, "expected_outputs": ["instances-model-grid.tif"]},
            "restore": {"argv": ["tool"], "cwd": "{skill_path}", "env": {}, "expected_outputs": ["instances-source-grid.tif"]},
        },
        "output": {"root": str(root / "derived"), "raw_model_grid_uri": "raw-model-grid.tif", "instance_model_grid_uri": "instances-model-grid.tif", "instance_source_grid_uri": "instances-source-grid.tif", "allow_overwrite": False},
        "verification": {"required_artifacts": [], "pilot_approved": False, "severe_issue_count": None, "checks": {}},
    }


class PipelineTests(unittest.TestCase):
    def test_archive_directory_resolves_full_commit(self):
        revision = "01c6e7aa3ad0e3c3334df8b129b0122724b6ad2e"
        self.assertEqual(
            adapter.resolve_repo_revision(Path("empanada-" + revision)),
            revision,
        )

    def test_v017_tracker_signature_fix_is_exact_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "pdl_inference3d.py"
            entrypoint.write_text(
                "update_trackers(rle_seg, index, trackers[axis_name], axis, stack)\n",
                encoding="utf-8",
            )
            executed, patches = adapter.prepare_entrypoint(
                entrypoint,
                adapter.TRACKER_SIGNATURE_FIX_COMMIT,
                root,
            )
            self.assertIn(
                "update_trackers(rle_seg, index, trackers[axis_name])",
                executed.read_text(encoding="utf-8"),
            )
            self.assertEqual(patches[0]["id"], "empanada-v0.1.7-update-trackers-signature")

    def test_audit_and_plan_preserve_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = base_config(root)
            report = pipeline.audit_config(config, root / "project.json")
            self.assertEqual(report["status"], "passed")
            plan = pipeline.create_plan(config)
            self.assertEqual(plan["model_grid"]["shape_zyx"], [8, 32, 32])
            self.assertEqual(plan["source_grid"]["physical_extent_nm_zyx"], [320.0, 512.0, 512.0])

    def test_preserve_z_rejects_changed_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = base_config(root)
            config["model"]["target_resolution_nm_zyx"][0] = 16
            with self.assertRaisesRegex(pipeline.SkillError, "z_policy is preserve"):
                pipeline.audit_config(config, root / "project.json")

    def test_anisotropic_orthoplane_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = base_config(root)
            config["inference"]["profiles"]["balanced"] = profile("orthoplane")
            with self.assertRaisesRegex(pipeline.SkillError, "Strongly anisotropic"):
                pipeline.audit_config(config, root / "project.json")

    def test_profile_selection_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = base_config(root); path = root / "project.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            pipeline.update_state(config, path, "pilot", "awaiting_review")
            sweep = pipeline.cmd_profile_sweep(config, path, execute=False)
            self.assertEqual(len(sweep["candidates"]), 2)
            with self.assertRaisesRegex(pipeline.SkillError, "No profile selected"):
                pipeline.selected_profile(config, path)
            for item in sweep["candidates"]:
                candidate = Path(item["job"]["expected_outputs"][0]); candidate.parent.mkdir(parents=True, exist_ok=True); candidate.write_bytes(b"labels")
            sweep["status"] = "completed"
            pipeline.write_json(pipeline.state_dir(config, path) / "profile-sweep.json", sweep)
            pipeline.update_state(config, path, "profile-sweep", "completed")
            selected = pipeline.cmd_select_profile(config, path, "balanced")
            self.assertEqual(selected["selected_profile"], "balanced")
            config["verification"]["pilot_approved"] = True
            path.write_text(json.dumps(config), encoding="utf-8")
            selected["config_sha256"] = pipeline.config_digest(config)
            pipeline.write_json(pipeline.state_dir(config, path) / "profile-selection.json", selected)
            job = pipeline.cmd_infer(config, path, execute=False)
            self.assertEqual(job["argv"][-1], "1")

    def test_verify_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); config = base_config(root)
            self.assertFalse(pipeline.verify(config, root / "project.json")["passed"])


if __name__ == "__main__":
    unittest.main()
