import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "neuroglancer_precomputed.py"
SPEC = importlib.util.spec_from_file_location("neuroglancer_precomputed", SCRIPT)
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


class FakeCloudVolume:
    registry = {}

    @staticmethod
    def create_new_info(num_channels, layer_type, data_type, encoding, resolution,
                        voxel_offset, chunk_size, volume_size, **kwargs):
        scale = {
            "encoding": encoding, "key": "0", "resolution": resolution,
            "voxel_offset": voxel_offset, "chunk_sizes": [chunk_size],
            "size": volume_size,
        }
        scale.update(kwargs)
        return {"type": layer_type, "data_type": data_type,
                "num_channels": num_channels, "scales": [scale]}

    def __init__(self, uri, info=None, **kwargs):
        self.path = Path(uri.removeprefix("file://"))
        if info is not None:
            FakeCloudVolume.registry[str(self.path)] = {"info": info, "data": None}
        self.record = FakeCloudVolume.registry[str(self.path)]

    def commit_info(self):
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "info").write_text(json.dumps(self.record["info"]), encoding="utf-8")
        scale = self.record["info"]["scales"][0]
        dtype = np.dtype(self.record["info"]["data_type"])
        self.record["data"] = np.zeros(tuple(scale["size"]) + (1,), dtype=dtype)

    def local_key(self, key):
        offset = self.record["info"]["scales"][0]["voxel_offset"]
        return tuple(slice(part.start - offset[index], part.stop - offset[index])
                     for index, part in enumerate(key[:3])) + tuple(key[3:])

    def __setitem__(self, key, value):
        self.record["data"][self.local_key(key)] = value

    def __getitem__(self, key):
        return self.record["data"][self.local_key(key)]


class PrecomputedPipelineTest(unittest.TestCase):
    def setUp(self):
        FakeCloudVolume.registry = {}
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)
        np.save(self.root / "labels.npy", self.source)
        self.config_path = self.root / "project.json"
        self.config_path.write_text(json.dumps({
            "precomputed": {
                "root": "precomputed",
                "datasets": [{
                    "id": "labels", "label": "Instances",
                    "source": {"path": "labels.npy", "axes": "zyx"},
                    "output": "labels", "layer_type": "segmentation",
                    "encoding": "raw", "resolution_nm_xyz": [8, 8, 40],
                    "voxel_offset_xyz": [10, 20, 30], "chunk_size_xyz": [2, 3, 2],
                    "segment_properties": {"1": "Object 1"},
                }],
            },
            "neuroglancer": {
                "base_url": "http://127.0.0.1:1337",
                "viewer_url": "https://neuroglancer-demo.appspot.com/",
                "layout": "xy",
            },
        }), encoding="utf-8")
        self.cfg = MOD.load_config(self.config_path)
        self.item = self.cfg["precomputed"]["datasets"][0]
        self.original_dep = MOD.require_cloudvolume
        MOD.require_cloudvolume = lambda: FakeCloudVolume

    def tearDown(self):
        MOD.require_cloudvolume = self.original_dep
        self.temp.cleanup()

    def test_inspect_axes_and_chunk_coverage(self):
        audit = MOD.inspect_dataset(self.cfg, self.item)
        self.assertEqual(audit["size_xyz"], [5, 4, 3])
        bounds = list(MOD.iter_bounds((5, 4, 3), (2, 3, 2)))
        self.assertEqual(sum((b[1] - b[0]) * (b[3] - b[2]) * (b[5] - b[4]) for b in bounds), 60)
        array, axes, _ = MOD.open_source(self.item)
        block = MOD.read_xyz(array, axes, (1, 4, 1, 3, 1, 3))
        self.assertTrue(np.array_equal(block, self.source[1:3, 1:3, 1:4].transpose(2, 1, 0)))

    def test_convert_verify_and_handoff(self):
        converted = MOD.convert_dataset(self.cfg, self.item)
        self.assertEqual(converted["size_xyz"], [5, 4, 3])
        verified = MOD.verify_dataset(self.cfg, self.item)
        self.assertTrue(verified["ok"])
        self.assertTrue(all(sample["exact_equal"] for sample in verified["samples"]))
        handoff = MOD.write_handoff(self.cfg, [self.item])
        self.assertEqual(handoff["layers"], 1)
        state = json.loads(Path(handoff["state"]).read_text(encoding="utf-8"))
        self.assertEqual(state["position"], [12.5, 22.0, 31.5])
        self.assertIn("precomputed://http://127.0.0.1:1337/labels", state["layers"][0]["source"])
        properties = json.loads((Path(self.item["_target"]) / "segment_properties" / "info").read_text())
        self.assertEqual(properties["inline"]["ids"], ["1"])

    def test_refuses_public_server_without_explicit_override(self):
        with self.assertRaisesRegex(ValueError, "non-loopback"):
            MOD.validate_serve_host("0.0.0.0")
        self.assertEqual(MOD.validate_serve_host("0.0.0.0", True), "0.0.0.0")

    def test_refuses_credentials_in_handoff_url(self):
        self.cfg["neuroglancer"]["base_url"] = "https://credential@example.org"
        with self.assertRaisesRegex(ValueError, "credentials"):
            MOD.build_neuroglancer_state(self.cfg, [self.item])

    def test_refuses_output_nested_in_source(self):
        source = self.root / "source.zarr"
        source.mkdir()
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data["precomputed"]["root"] = "source.zarr"
        data["precomputed"]["datasets"][0]["source"] = {
            "path": "source.zarr", "format": "zarr", "axes": "zyx"
        }
        nested = self.root / "unsafe.json"
        nested.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "nested inside its source"):
            MOD.load_config(nested)

    def test_compressed_segmentation_block_divides_chunk(self):
        self.item["encoding"] = "compressed_segmentation"
        self.item["chunk_size_xyz"] = [10, 12, 3]
        array, axes, _ = MOD.open_source(self.item)
        info = MOD.expected_info(FakeCloudVolume, self.item, array, axes)
        self.assertEqual(info["scales"][0]["compressed_segmentation_block_size"], [5, 6, 3])


if __name__ == "__main__":
    unittest.main()
