import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("advisor", ROOT / "scripts" / "em_annotation_advisor.py")
advisor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(advisor)


def config():
    return {
        "project": {"id": "synthetic"},
        "source": {
            "uri": "memory://synthetic",
            "axes": "zyx",
            "shape_zyx": [2, 4, 8],
            "voxel_size_nm_zyx": [10, 2, 2],
        },
        "embedding": {
            "model_repository": "https://example.org/model",
            "model_commit": "abc123",
            "checkpoint_sha256": "0" * 64,
            "dimension": 3,
        },
        "tiling": {
            "patch_shape_zyx": [1, 2, 2],
            "stride_zyx": [1, 2, 2],
            "boundary_mode": "valid",
        },
        "selection": {
            "max_subvolumes": 2,
            "annotation_budget_voxels": 32,
            "candidate_windows_patches_zyx": [[1, 1, 1], [1, 1, 2]],
            "expected_subvolume_shapes_zyx": [[1, 2, 2], [1, 2, 4]],
            "k_neighbors": 3,
            "metric": "euclidean",
            "cost_exponent": 1.0,
            "disallow_patch_overlap": True,
            "max_exact_patches": 100,
            "max_working_memory_mib": 1,
        },
        "guards": {"excluded_bboxes_zyx": [], "holdout_bboxes_zyx": []},
    }


class AdvisorTests(unittest.TestCase):
    def test_manifest_geometry(self):
        manifest = advisor.build_manifest(config())
        self.assertEqual(manifest["patch_grid_shape_zyx"], [2, 2, 4])
        self.assertEqual(manifest["patch_count"], 16)
        self.assertEqual(manifest["candidate_count"], 28)
        self.assertEqual(manifest["derived_subvolume_shapes_zyx"], [[1, 2, 2], [1, 2, 4]])
        self.assertEqual({tuple(c["derived_shape_zyx"]) for c in manifest["candidates"]}, {(1, 2, 2), (1, 2, 4)})

    def test_holdout_removes_intersections(self):
        cfg = config()
        cfg["guards"]["holdout_bboxes_zyx"] = [[[1, 0, 0], [2, 4, 8]]]
        manifest = advisor.build_manifest(cfg)
        self.assertEqual(manifest["candidate_count"], 14)
        self.assertEqual(manifest["guard_rejected_candidate_count"], 14)
        for row in manifest["candidates"]:
            self.assertEqual(row["bbox_zyx"][0][0], 0)

    def test_selection_is_review_required_and_nonoverlapping(self):
        cfg = config()
        manifest = advisor.build_manifest(cfg)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "embeddings.npy"
            x = np.array([[z, y, x] for z in range(2) for y in range(2) for x in range(4)], dtype=np.float32)
            np.save(path, x)
            draft = advisor.select_candidates(cfg, manifest, path)
        self.assertEqual(draft["status"], "DRAFT_REQUIRES_HUMAN_REVIEW")
        self.assertEqual(len(draft["selected_subvolumes"]), 2)
        first = set(draft["selected_subvolumes"][0]["patch_ids"])
        second = set(draft["selected_subvolumes"][1]["patch_ids"])
        self.assertFalse(first & second)
        rates = [r["coverage_rate"] for r in draft["coverage_curve"]]
        self.assertEqual(rates, sorted(rates))
        self.assertLessEqual(draft["annotation_cost_voxels"], cfg["selection"]["annotation_budget_voxels"])
        self.assertIn("derived_shape_zyx", draft["selected_subvolumes"][0])

    def test_budget_can_force_small_candidate(self):
        cfg = config()
        cfg["selection"]["annotation_budget_voxels"] = 4
        cfg["selection"]["max_subvolumes"] = 1
        manifest = advisor.build_manifest(cfg)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "embeddings.npy"
            np.save(path, np.eye(16, 3, dtype=np.float32))
            draft = advisor.select_candidates(cfg, manifest, path)
        self.assertEqual(draft["selected_subvolumes"][0]["derived_shape_zyx"], [1, 2, 2])
        self.assertEqual(draft["annotation_cost_voxels"], 4)

    def test_finalize_requires_complete_review(self):
        draft = {
            "status": "DRAFT_REQUIRES_HUMAN_REVIEW",
            "selected_subvolumes": [
                {"candidate_id": "a", "review_status": "pending"},
                {"candidate_id": "b", "review_status": "pending"},
            ],
        }
        incomplete = {
            "reviewer": "Expert",
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "decisions": [{"candidate_id": "a", "decision": "accept"}],
        }
        with self.assertRaises(advisor.AdviceError):
            advisor.finalize(draft, incomplete)
        complete = {
            "reviewer": "Expert",
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "decisions": [
                {"candidate_id": "a", "decision": "accept", "reason": "ok"},
                {"candidate_id": "b", "decision": "reject", "reason": "fold"},
            ],
        }
        result = advisor.finalize(draft, complete)
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected_count"], 1)

    def test_axis_order_fails_closed(self):
        cfg = config()
        cfg["source"]["axes"] = "xyz"
        with self.assertRaises(advisor.AdviceError):
            advisor.validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
