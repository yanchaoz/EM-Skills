"""Add a calibrated camera-plane scale bar without modifying the raw render."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def annotate(image_path, manifest_path, length_um, output_dir, font_path=None):
    image_path, manifest_path = Path(image_path).resolve(), Path(manifest_path).resolve()
    out = Path(output_dir).resolve()
    if out.exists():
        raise FileExistsError('Use a new scale-bar output directory')
    if image_path.is_relative_to(out) or manifest_path.is_relative_to(out):
        raise ValueError('Output directory cannot contain the inputs')
    if not math.isfinite(length_um) or length_um <= 0:
        raise ValueError('length_um must be finite and positive')
    metadata = json.loads(manifest_path.read_text(encoding='utf-8'))
    if metadata.get('status') != 'complete' or metadata.get('completed') is not True:
        raise ValueError('A completed render manifest is required')
    image_hash = digest(image_path)
    if image_hash not in {item['sha256'] for item in metadata.get('outputs', [])}:
        raise ValueError('Input image is not an unchanged output of this render manifest')
    projection = metadata['camera_projection']
    if projection.get('type') != 'ORTHO':
        raise ValueError('Only verified orthographic camera projections are supported')
    span_mm = float(projection['world_screen_width_mm'])
    if not math.isfinite(span_mm) or span_mm <= 0:
        raise ValueError('Invalid camera screen width')
    image = Image.open(image_path).convert('RGBA')
    width, height = image.size
    if [width, height] != metadata['render']['resolution']:
        raise ValueError('Image dimensions do not match the original projection')
    ideal_px = length_um / 1000 / span_mm * width
    bar_px = round(ideal_px)
    if not 8 <= bar_px <= width * .45:
        raise ValueError('Choose a length producing a scale bar between 8 pixels and 45% of width')
    margin = max(12, round(min(width, height) * .06))
    thickness = max(2, round(height / 650))
    font_size = max(12, round(height * .02))
    if font_path:
        font = ImageFont.truetype(str(font_path), font_size)
    else:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError as exc:
            raise RuntimeError('Pillow >= 10.1 or an explicit --font TrueType file is required') from exc
    label = f'{length_um:g} µm'
    draw = ImageDraw.Draw(image)
    text_bounds = draw.textbbox((0, 0), label, font=font)
    text_width = text_bounds[2] - text_bounds[0]
    text_height = text_bounds[3] - text_bounds[1]
    x1, y = width - margin, height - margin
    x0 = x1 - bar_px
    text_x = round((x0 + x1 - text_width) / 2)
    text_y = y - max(5, round(height * .012)) - text_height - text_bounds[1]
    if text_x < 0 or text_x + text_width >= width or text_y < 0:
        raise ValueError('Scale label would fall outside the image')
    color = (45, 45, 45, 255)
    draw.line((x0, y, x1, y), fill=color, width=thickness)
    draw.text((text_x, text_y), label, fill=color, font=font)
    out.mkdir(parents=True)
    destination = out / 'figure_with_scale.png'
    image.save(destination)
    report = dict(schema_version=1, input_image=dict(path=str(image_path), sha256=image_hash),
        input_manifest=dict(path=str(manifest_path), sha256=digest(manifest_path)),
        length_um=length_um, ideal_length_px=ideal_px, drawn_endpoint_distance_px=bar_px,
        represented_length_um=bar_px / width * span_mm * 1000,
        endpoints_px=[[x0, y], [x1, y]], world_screen_width_mm=span_mm,
        interpretation='Orthographic camera-plane length, not a foreshortened specimen-axis measurement.',
        output=dict(path=str(destination), sha256=digest(destination)), raw_render_modified=False,
        note='Annotation placement must be visually checked for overlap with tissue.')
    (out / 'scale_bar.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True)
    p.add_argument('--render-manifest', required=True)
    p.add_argument('--length-um', required=True, type=float)
    p.add_argument('--out', required=True)
    p.add_argument('--font')
    args = p.parse_args()
    report = annotate(args.image, args.render_manifest, args.length_um, args.out, args.font)
    print(report['output']['path'])


if __name__ == '__main__':
    main()
