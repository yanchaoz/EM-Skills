"""Compare scientific renders or retain an authorized local geometry revision."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_pair(before, after):
    before, after = Path(before).resolve(), Path(after).resolve()
    with Image.open(before) as image:
        mode = image.mode
        a = np.asarray(image.convert('RGBA'))
    with Image.open(after) as image:
        b = np.asarray(image.convert('RGBA'))
    if a.shape != b.shape:
        raise ValueError('Images must have identical dimensions and coordinate framing')
    return before, after, a, b, mode


def compare_arrays(a, b):
    difference = np.abs(a.astype(np.int16) - b.astype(np.int16))
    changed = np.any(difference != 0, axis=-1)
    ys, xs = np.where(changed)
    return dict(changed_pixels=int(changed.sum()),
                max_channel_difference=int(difference.max()),
                mean_absolute_channel_difference=float(difference.mean()),
                changed_box_xyxy=None if not xs.size else
                [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])


def fresh_file(path, sources=()):
    path = Path(path).resolve()
    if path in {Path(p).resolve() for p in sources}:
        raise ValueError('Output aliases an input')
    if path.exists():
        raise FileExistsError(f'Preserve existing artifact: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def preserve(before, after, rectangle, tolerance, output):
    before, after, a, b, mode = read_pair(before, after)
    if not 0 <= tolerance <= 255:
        raise ValueError('Tolerance must be between 0 and 255')
    x0, y0, x1, y1 = rectangle
    h, w = a.shape[:2]
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError('Rectangle must be an in-bounds half-open XYXY box')
    region = np.zeros((h, w), bool)
    region[y0:y1, x0:x1] = True
    if region.all():
        raise ValueError('A local preservation mask must leave an unchanged region')
    difference = np.max(np.abs(a.astype(np.int16) - b.astype(np.int16)), axis=-1)
    outside_max = int(difference[~region].max())
    seam = np.zeros_like(region)
    seam[y0:y1, x0] = seam[y0:y1, x1 - 1] = True
    seam[y0, x0:x1] = seam[y1 - 1, x0:x1] = True
    seam_max = int(difference[seam].max())
    if outside_max > tolerance or seam_max > tolerance:
        raise ValueError(f'Unjustified preservation mask: outside max {outside_max}, '
                         f'boundary max {seam_max}, allowed {tolerance}')
    output = Path(output).resolve()
    if output in (before, after) or output.exists():
        raise FileExistsError('Use a new output directory; original inputs are preserved')
    # Validate everything before creating any delivery artifacts.
    output.mkdir(parents=True)
    result = a.copy()
    result[region] = b[region]
    assert np.array_equal(result[~region], a[~region])
    final = Image.fromarray(result)
    if mode == 'RGB':
        final = final.convert('RGB')
    final.save(output / 'preserved.png')
    Image.fromarray((region * 255).astype(np.uint8)).save(output / 'mask.png')
    report = dict(status='verified', operation='same-coordinate local render composition',
        not_single_untouched_render=True, rectangle_xyxy=rectangle, tolerance=tolerance,
        before=dict(path=str(before), sha256=sha256(before)),
        raw_rerender=dict(path=str(after), sha256=sha256(after)),
        comparison=compare_arrays(a, b), outside_max_channel_difference=outside_max,
        boundary_max_channel_difference=seam_max, unchanged_outside_mask=True,
        scientific_mask_justification='Must be supplied by the caller from approved geometry; not inferred by this tool',
        output_sha256=sha256(output / 'preserved.png'), mask_sha256=sha256(output / 'mask.png'))
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('compare', 'preserve'):
        p = sub.add_parser(name)
        p.add_argument('--before', required=True)
        p.add_argument('--after', required=True)
        p.add_argument('--out', required=True)
        if name == 'preserve':
            p.add_argument('--rectangle', type=int, nargs=4, required=True, metavar=('X0', 'Y0', 'X1', 'Y1'))
            p.add_argument('--tolerance', type=int, required=True)
    m = sub.add_parser('manifest')
    m.add_argument('--files', nargs='+', required=True)
    m.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.command == 'preserve':
        report = preserve(args.before, args.after, args.rectangle, args.tolerance, args.out)
    elif args.command == 'compare':
        before, after, a, b, _ = read_pair(args.before, args.after)
        report = dict(before_sha256=sha256(before), after_sha256=sha256(after),
                      size_wh=[a.shape[1], a.shape[0]], **compare_arrays(a, b))
        out = fresh_file(args.out, [before, after])
        out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    else:
        paths = [Path(f).resolve() for f in args.files]
        if not all(p.is_file() for p in paths):
            raise ValueError('Every manifest input must be an existing regular file')
        out = fresh_file(args.out, paths)
        report = dict(files=[dict(path=str(p), bytes=p.stat().st_size, sha256=sha256(p)) for p in paths])
        out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
