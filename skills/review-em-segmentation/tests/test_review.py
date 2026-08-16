import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_em_segmentation.py"
SPEC = importlib.util.spec_from_file_location("review_em_segmentation", SCRIPT)
reviewer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(reviewer)


class MetricTests(unittest.TestCase):
    def test_foreground_metrics_perfect_and_partial(self):
        truth = np.array([[0, 1], [0, 1]], dtype=np.uint8)
        perfect = reviewer.foreground_metrics(truth, truth)
        partial = reviewer.foreground_metrics(np.array([[0, 1], [0, 0]]), truth)
        self.assertEqual(perfect["dice"], 1.0)
        self.assertAlmostEqual(partial["dice"], 2 / 3)
        self.assertAlmostEqual(partial["iou"], 0.5)

    def test_instance_matching_penalizes_merge(self):
        truth = np.array([[1, 1, 0, 2, 2]], dtype=np.uint16)
        perfect = reviewer.instance_matching(truth, truth, 0.5)
        merged = reviewer.instance_matching(np.array([[1, 1, 0, 1, 1]], dtype=np.uint16), truth, 0.5)
        self.assertEqual(perfect["f1"], 1.0)
        self.assertLess(merged["f1"], perfect["f1"])

    def test_rejects_fractional_labels(self):
        with self.assertRaisesRegex(ValueError, "non-integral"):
            reviewer.validate_labels(np.array([[0.0, 0.5]]), "candidate")

    def test_rejects_fractional_offset(self):
        with self.assertRaisesRegex(ValueError, "integer value"):
            reviewer.validate_offset([0, 1.5, 0], "zyx")

    def test_scale_bar_is_bounded_and_nonzero(self):
        self.assertGreater(reviewer.scale_bar_um(0.5), 0)
        self.assertLessEqual(reviewer.scale_bar_um(10), 2.8)

    @unittest.skipIf(importlib.util.find_spec("tifffile") is None, "tifffile is not installed")
    def test_loads_tiff_labels(self):
        import tifffile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.tif"
            expected = np.arange(24, dtype=np.uint16).reshape(2, 3, 4)
            tifffile.imwrite(path, expected)
            np.testing.assert_array_equal(reviewer.load_array(path), expected)


class EndToEndTests(unittest.TestCase):
    def test_review_ranks_only_with_ground_truth_and_withholds_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = np.arange(3 * 16 * 16, dtype=np.float32).reshape(3, 16, 16)
            truth = np.zeros(raw.shape, dtype=np.uint16)
            truth[:, 2:7, 2:7] = 1
            truth[1:, 10:14, 10:14] = 2
            good = truth.copy()
            poor = np.zeros_like(truth)
            poor[:, 1:9, 1:9] = 1
            for name, array in (("raw", raw), ("truth", truth), ("good", good), ("poor", poor)):
                np.save(root / f"{name}.npy", array)
            config = root / "project.yaml"
            config.write_text(
                "\n".join([
                    "project_id: synthetic",
                    "raw:",
                    "  path: raw.npy",
                    "  source_id: synthetic:roi:v1",
                    "  grid_id: source-grid",
                    "  axes: zyx",
                    "  resolution_nm: [40, 8, 8]",
                    "  offset_vox: [0, 0, 0]",
                    "candidates:",
                    "  - {name: good, path: good.npy, kind: instance, grid_id: source-grid, provenance: synthetic-good}",
                    "  - {name: poor, path: poor.npy, kind: instance, grid_id: source-grid, provenance: synthetic-poor}",
                    "ground_truth:",
                    "  path: truth.npy",
                    "  kind: instance",
                    "  grid_id: source-grid",
                    "  provenance: synthetic frozen truth",
                    "review:",
                    "  output_root: output",
                    "  axis: xy",
                    "  instance_iou_threshold: 0.5",
                ]) + "\n",
                encoding="utf-8",
            )
            report = reviewer.review(config)
            self.assertEqual(report["ranking"][0]["name"], "good")
            self.assertEqual(report["scientific_approval"], "withheld")
            self.assertTrue((root / "output" / "review-comparison.png").exists())

    def test_review_without_truth_does_not_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = np.zeros((12, 12), dtype=np.uint8)
            labels = np.zeros_like(raw)
            labels[2:6, 2:6] = 1
            np.save(root / "raw.npy", raw)
            np.save(root / "labels.npy", labels)
            config = root / "project.yaml"
            config.write_text(
                "\n".join([
                    "project_id: no-truth",
                    "raw: {path: raw.npy, source_id: synthetic:2d:v1, grid_id: source-grid, axes: yx, resolution_nm: [8, 8], offset_vox: [0, 0]}",
                    "candidates:",
                    "  - {name: candidate, path: labels.npy, kind: semantic, grid_id: source-grid, provenance: synthetic-candidate}",
                    "review: {output_root: output, axis: xy}",
                ]) + "\n",
                encoding="utf-8",
            )
            report = reviewer.review(config)
            self.assertIsNone(report["ranking"])
            self.assertEqual(report["evidence_state"], "descriptive_qc_only")

    def test_finalize_requires_human_attribution_and_preserves_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "review-report.json"
            report_path.write_text(json.dumps({"scientific_approval": "withheld"}), encoding="utf-8")
            args = argparse.Namespace(
                report=report_path,
                decision="approved",
                reviewer="expert-1",
                basis="overlay and holdout metrics reviewed",
                claim_scope="declared synthetic holdout",
                output=None,
                force=False,
            )
            record = reviewer.finalize(args)
            self.assertFalse(record["automated_selection"])
            self.assertEqual(json.loads(report_path.read_text())["scientific_approval"], "withheld")


if __name__ == "__main__":
    unittest.main()
