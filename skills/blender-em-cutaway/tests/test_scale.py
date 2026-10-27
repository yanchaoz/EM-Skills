import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from annotate_scale import annotate, digest


class ScaleTests(unittest.TestCase):
    def fixture(self, root):
        image, manifest = root / 'render.png', root / 'render_manifest.json'
        Image.new('RGBA', (1000, 600), 'white').save(image)
        cfg = dict(status='complete', completed=True, render=dict(resolution=[1000, 600]),
                   camera_projection=dict(type='ORTHO', world_screen_width_mm=1.0),
                   outputs=[dict(sha256=digest(image))])
        manifest.write_text(json.dumps(cfg), encoding='utf-8')
        return image, manifest, cfg

    def test_non_square_projection_and_source_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            image, manifest, cfg = self.fixture(root)
            initial = digest(image)
            result = annotate(image, manifest, 100, root / 'annotated')
            self.assertEqual(result['drawn_endpoint_distance_px'], 100)
            self.assertEqual(result['represented_length_um'], 100)
            self.assertEqual(initial, digest(image))
            with self.assertRaises(FileExistsError):
                annotate(image, manifest, 100, root / 'annotated')

    def test_rejects_unbound_image_or_unfinished_projection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            image, manifest, cfg = self.fixture(root)
            cfg['status'] = 'started'
            manifest.write_text(json.dumps(cfg), encoding='utf-8')
            with self.assertRaises(ValueError):
                annotate(image, manifest, 100, root / 'bad')
            cfg['status'] = 'complete'
            manifest.write_text(json.dumps(cfg), encoding='utf-8')
            Image.new('RGBA', (1000, 600), 'black').save(image)
            with self.assertRaises(ValueError):
                annotate(image, manifest, 100, root / 'bad')
            self.assertFalse((root / 'bad').exists())


if __name__ == '__main__':
    unittest.main()
