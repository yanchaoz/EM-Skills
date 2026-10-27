import importlib.util
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location('verify_export', Path(__file__).parents[1] / 'scripts/verify_export.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ExportTests(unittest.TestCase):
    def test_preserves_unrelated_pixels_and_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            a = np.full((16, 20, 3), 100, np.uint8)
            b = a.copy(); b[6:8, 8:10] = 240; b[1, 1] = 101
            Image.fromarray(a).save(p / 'old.png'); Image.fromarray(b).save(p / 'new.png')
            h = mod.sha256(p / 'old.png')
            result = mod.preserve(p/'old.png', p/'new.png', [4, 3, 15, 12], 1, p/'out')
            delivered = np.array(Image.open(p/'out/preserved.png'))
            self.assertEqual(delivered[1, 1, 0], 100)
            self.assertEqual(delivered[6, 8, 0], 240)
            self.assertEqual(h, mod.sha256(p/'old.png'))
            self.assertTrue(result['unchanged_outside_mask'])
            self.assertTrue((p/'out/mask.png').exists())

    def test_rejects_substantial_change_outside_mask_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            a = np.zeros((10, 10, 3), np.uint8); b = a.copy(); b[0, 0] = 20
            Image.fromarray(a).save(p/'a.png'); Image.fromarray(b).save(p/'b.png')
            with self.assertRaises(ValueError):
                mod.preserve(p/'a.png', p/'b.png', [2, 2, 8, 8], 2, p/'out')
            self.assertFalse((p/'out').exists())

    def test_rejects_seam_and_shape_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            a = np.zeros((10, 10, 3), np.uint8); b = a.copy(); b[2, 3] = 100
            Image.fromarray(a).save(p/'a.png'); Image.fromarray(b).save(p/'b.png')
            with self.assertRaises(ValueError):
                mod.preserve(p/'a.png', p/'b.png', [2, 2, 8, 8], 2, p/'out')
            Image.fromarray(a[:8]).save(p/'short.png')
            with self.assertRaises(ValueError):
                mod.read_pair(p/'a.png', p/'short.png')

    def test_rejects_overwriting_an_existing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); f=p/'input.txt'; f.write_text('source')
            with self.assertRaises(ValueError): mod.fresh_file(f, [f])
            with self.assertRaises(FileExistsError): mod.fresh_file(f)
            self.assertEqual(f.read_text(), 'source')


if __name__ == '__main__': unittest.main()
