"""Optional real OpenVDB roundtrip; skipped explicitly when bindings are absent."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from cutaway_core import display_layer, load_config, open_source, sha256
from make_demo import make_demo
from prepare_volume import import_vdb, prepare
from render_blender import native_transform, validate_cache


class PreparationTest(unittest.TestCase):
    def test_preparation_cannot_overwrite_its_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_demo(tmp)
            cfg = json.loads(path.read_text())
            # Use absolute inputs so the configuration may live in a separate
            # prepared directory without relocating any original data.
            cfg["source"]["path"] = str(Path(tmp)/"synthetic.npy")
            cfg["mesh"]["path"] = str(Path(tmp)/"synthetic_core.obj")
            out = Path(tmp)/"prepared"
            out.mkdir()
            target = out/"manifest.json"
            target.write_text(json.dumps(cfg))
            with self.assertRaisesRegex(ValueError,"project configuration"):
                prepare(target,output=out,overwrite=True)

    def test_actual_native_vdb_roundtrip(self):
        try:
            vdb = import_vdb()
        except RuntimeError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as tmp:
            path = make_demo(tmp)
            cfg = load_config(path)
            before = sha256(cfg["source"]["path"])
            m = prepare(path,sample_count=64)
            self.assertEqual(before,sha256(cfg["source"]["path"]))
            self.assertFalse(m["vdb"]["geometry_pruned"])
            self.assertEqual(m["verification"]["independent_serialized_readback_samples"],72)
            raw = open_source(cfg)
            grid = vdb.read(m["vdb"]["path"],"em_linear")
            actual = grid.getConstAccessor()
            for z in (0,15,31):
                expected,_,_ = display_layer(cfg,raw[z])
                for y,x in ((0,0),(12,7),(71,47)):
                    self.assertEqual(actual.getValue((x,y,z)),float(expected[y,x]))
            # A cut region is intentionally retained in cache, for later recuts.
            self.assertGreater(actual.getValue((30,30,0)),0)
            # Cache indices are independent of all renderer-side clipping/reflection.
            cfg["geometry"]["reflect_z"] = False
            cfg["geometry"]["remove_regions"] = []
            reused,_ = validate_cache(cfg,m["vdb"]["path"])
            t = native_transform(reused["source"],reused["source"]["shape_zyx"],False)
            self.assertGreater(t["volume_scale_xyz"][2],0)
            self.assertTrue(reused["transform"]["reflect_z"])  # Preparation-time provenance only.
            with self.assertRaises(FileExistsError): prepare(path)
            with self.assertRaises(ValueError): prepare(path, output=tmp)
            del raw  # Release Windows mmap before TemporaryDirectory cleanup.


if __name__ == "__main__":
    unittest.main()
