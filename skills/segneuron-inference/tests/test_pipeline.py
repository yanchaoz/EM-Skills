import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "segneuron_pipeline.py"
SPEC = importlib.util.spec_from_file_location("segneuron_pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)


def base_config(root: Path) -> dict:
    source = root / "raw.npy"
    source.write_bytes(b"test-source")
    return {
        "project": {"id": "test-volume"},
        "source": {
            "uri": str(source), "format": "npy", "axis_order": "zyx",
            "shape_zyx": [25, 260, 270], "resolution_nm_zyx": [40, 8, 8],
            "offset_vox_zyx": [10, 20, 30], "bbox_vox_zyx": [0, 0, 0, 25, 260, 270],
            "read_only": True, "identity": "fixture-v1",
        },
        "model": {
            "repository": "yanchaoz/SegNeuron", "repo_path": str(root),
            "repo_commit": "0123456789abcdef", "checkpoint": str(root / "missing-remote-mounted.pth"),
            "checkpoint_sha256": "0" * 64,
            "profile": {
                "target_resolution_nm_zyx": [40, 8, 8], "validated_xy_nm": [5, 10],
                "z_policy": "preserve", "normalization": "uint8-div255",
                "patch_zyx": [20, 128, 128], "halo_zyx": [4, 16, 16],
            },
        },
        "planning": {
            "tile_core_zyx": [12, 96, 96], "max_end_error_nm": 4,
            "pilot_rois": [[0, 0, 0, 20, 128, 128]],
            "estimated_bytes_per_affinity_voxel": 12,
            "estimated_bytes_per_instance_voxel": 8,
        },
        "commands": {
            "infer": {
                "argv": ["tool", "--config", "{config_path}"], "cwd": str(root), "env": {},
                "expected_outputs": ["affinities"],
            },
            "beta_sweep": {
                "argv": ["tool", "--beta", "{beta}", "--tag", "{beta_tag}"],
                "cwd": str(root), "env": {}, "expected_outputs": ["beta-{beta_tag}.npy"],
            },
            "instance": {
                "argv": ["tool", "--beta", "{selected_beta}"], "cwd": str(root), "env": {},
                "expected_outputs": ["instances"],
            },
            "restore": {"argv": ["tool"], "cwd": str(root), "env": {}, "expected_outputs": ["restored"]},
        },
        "instance": {
            "method": "frmc", "scope": "whole-volume", "label_dtype": "uint64", "background_id": 0,
            "beta_sweep": {"values": [0.1, 0.25, 0.5]},
            "global_reconciliation": {"required": False, "completed": False, "artifact": ""},
        },
        "output": {
            "root": str(root / "derived"), "affinity_uri": "affinities",
            "instance_model_grid_uri": "instances", "instance_source_grid_uri": "restored",
            "allow_overwrite": False,
        },
        "verification": {
            "required_artifacts": [], "pilot_approved": False, "severe_issue_count": None,
            "checks": {
                "bounds_match": False, "dtype_safe": False, "ids_valid": False,
                "seams_reviewed": False, "provenance_complete": False,
                "orthogonal_views_reviewed": False,
            },
        },
    }


class PipelineTests(unittest.TestCase):
    def test_audit_and_plan_preserve_physical_extent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config_path = root / "project.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            audit = pipeline.audit_config(config, config_path)
            self.assertEqual(audit["status"], "passed")
            plan = pipeline.create_plan(config, config_path)
            self.assertEqual(plan["model_grid"]["shape_zyx"], [25, 260, 270])
            self.assertEqual(plan["model_grid"]["physical_extent_nm_zyx"], [1000.0, 2080.0, 2160.0])
            self.assertGreater(plan["tiling"]["tile_count"], 1)

    def test_preserve_z_rejects_changed_z_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config["model"]["profile"]["target_resolution_nm_zyx"][0] = 8
            with self.assertRaisesRegex(pipeline.SkillError, "z_policy is preserve"):
                pipeline.audit_config(config, root / "project.json")

    def test_mutable_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config["model"]["repo_commit"] = "main"
            with self.assertRaisesRegex(pipeline.SkillError, "pinned commit"):
                pipeline.audit_config(config, root / "project.json")

    def test_dry_run_renders_argv_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config_path = root / "project.json"
            job = pipeline.run_job("infer", config, config_path, execute=False)
            self.assertEqual(job["status"], "planned")
            self.assertEqual(job["argv"][1], "--config")
            self.assertEqual(job["argv"][2], str(config_path))
            self.assertTrue((root / "derived" / "_segneuron_skill" / "jobs" / "infer.json").exists())

    def test_audit_plan_pilot_state_progression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config_path = root / "project.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            pipeline.cmd_audit(config, config_path)
            pipeline.cmd_plan(config, config_path)
            pilot = pipeline.cmd_pilot(config, config_path, execute=False)
            self.assertEqual(pilot["status"], "awaiting_review")
            state = pipeline.read_state(config, config_path)
            self.assertEqual(state["stages"]["audit"]["status"], "completed")
            self.assertEqual(state["stages"]["plan"]["status"], "completed")
            self.assertEqual(state["stages"]["pilot"]["status"], "awaiting_review")

    def test_per_block_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config["instance"]["scope"] = "per-block"
            with self.assertRaisesRegex(pipeline.SkillError, "require global reconciliation"):
                pipeline.audit_config(config, root / "project.json")

    def test_beta_values_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config["instance"]["beta_sweep"]["values"] = [0.25, 1.0]
            with self.assertRaisesRegex(pipeline.SkillError, "strictly between 0 and 1"):
                pipeline.audit_config(config, root / "project.json")

    def test_beta_sweep_requires_explicit_selection_before_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            config_path = root / "project.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            pipeline.update_state(config, config_path, "infer", "completed")
            sweep = pipeline.cmd_beta_sweep(config, config_path, execute=False)
            self.assertEqual([item["beta"] for item in sweep["candidates"]], [0.1, 0.25, 0.5])
            self.assertIn("0.25", sweep["candidates"][1]["job"]["argv"])
            with self.assertRaisesRegex(pipeline.SkillError, "No beta has been selected"):
                pipeline.cmd_operation("instance", config, config_path, execute=False)

            for candidate in sweep["candidates"]:
                Path(candidate["job"]["expected_outputs"][0]).write_bytes(b"candidate")
            sweep["status"] = "completed"
            pipeline.write_json(pipeline.state_dir(config, config_path) / "beta-sweep.json", sweep)
            pipeline.update_state(config, config_path, "beta-sweep", "completed")
            selection = pipeline.cmd_select_beta(config, config_path, 0.25)
            self.assertEqual(selection["selected_beta"], 0.25)
            job = pipeline.cmd_operation("instance", config, config_path, execute=False)
            self.assertEqual(job["argv"][-1], "0.25")

    def test_verification_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = base_config(root)
            report = pipeline.verify_project(config, root / "project.json")
            self.assertFalse(report["passed"])
            self.assertFalse(report["checks"]["review"]["passed"])


if __name__ == "__main__":
    unittest.main()
