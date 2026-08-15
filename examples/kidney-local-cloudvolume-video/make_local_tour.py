#!/usr/bin/env python3
"""Render and verify a bounded kidney EM mask/overlay/density story.

The input is produced by ``export_kidney_story_assets.py``.  The presentation
scope is deliberately bounded: one 1 x 1 mm context ROI and four smaller
200 x 112.5 um ROIs.  A whole-kidney image is never reconstructed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


WIDTH, HEIGHT, FPS = 1920, 1080, 24
BG = (13, 17, 22)
PANEL = (24, 30, 38)
TEXT = (244, 247, 250)
MUTED = (174, 188, 201)
ACCENT = (89, 220, 238)
LAYERS = (
    ("nuclei", "Nuclei"),
    ("mitochondria", "Mitochondria"),
    ("basement_membrane", "Basement membrane"),
    ("lysosomes", "Lysosomes"),
)


@dataclass
class State:
    key: str
    title: str
    frame: np.ndarray
    hold_seconds: float


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def put(frame, text, xy, scale=0.8, color=TEXT, thickness=2):
    cv2.putText(frame, str(text), xy, cv2.FONT_HERSHEY_SIMPLEX, scale,
                color, thickness, cv2.LINE_AA)


def translucent_rect(frame, p0, p1, color=PANEL, alpha=0.88):
    overlay = frame.copy()
    cv2.rectangle(overlay, p0, p1, color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)


def gray_bgr(raw):
    return cv2.cvtColor(raw.astype(np.uint8), cv2.COLOR_GRAY2BGR)


def fit_image(image, width, height, background=BG):
    ih, iw = image.shape[:2]
    scale = min(width / iw, height / ih)
    nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.full((height, width, 3), background, np.uint8)
    x, y = (width - nw) // 2, (height - nh) // 2
    canvas[y:y + nh, x:x + nw] = resized
    return canvas, (x, y, nw, nh)


def header(frame, eyebrow, title, subtitle=None):
    translucent_rect(frame, (0, 0), (WIDTH, 142), color=(10, 14, 19), alpha=0.96)
    put(frame, eyebrow.upper(), (46, 44), 0.55, ACCENT, 2)
    put(frame, title, (46, 98), 1.25, TEXT, 3)
    if subtitle:
        put(frame, subtitle, (WIDTH - 760, 87), 0.62, MUTED, 2)
    cv2.line(frame, (46, 125), (WIDTH - 46, 125), (57, 69, 81), 2, cv2.LINE_AA)


def footer(frame, text="Bounded kidney ROI | CloudVolume precomputed data"):
    translucent_rect(frame, (0, HEIGHT - 54), (WIDTH, HEIGHT), color=(10, 14, 19), alpha=0.94)
    put(frame, text, (46, HEIGHT - 18), 0.52, MUTED, 1)


def layer_color_bgr(record, key):
    rgb = record["layers"][key]["color_rgb"]
    return tuple(int(x) for x in reversed(rgb))


def overlay(raw, masks, record, alpha=0.56):
    result = gray_bgr(raw).astype(np.float32)
    for key, _ in LAYERS:
        mask = masks[key].astype(bool)
        color = np.asarray(layer_color_bgr(record, key), np.float32)
        result[mask] = (1.0 - alpha) * result[mask] + alpha * color
    return np.clip(result, 0, 255).astype(np.uint8)


def draw_scale_bar(frame, image_box, fov_um_x, bar_um):
    x, y, w, h = image_box
    px = max(40, round(w * bar_um / fov_um_x))
    x1, y1 = x + w - 38, y + h - 38
    x0 = x1 - px
    cv2.line(frame, (x0, y1), (x1, y1), (255, 255, 255), 7, cv2.LINE_AA)
    put(frame, f"{bar_um:g} um", (x0, y1 - 18), 0.55, TEXT, 2)


def raw_state(prefix, raw, record, scope_label):
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    image, box = fit_image(gray_bgr(raw), 1370, 870)
    frame[156:1026, :1370] = image
    translucent_rect(frame, (1400, 174), (1880, 954), alpha=0.95)
    put(frame, "FIELD OF VIEW", (1440, 230), 0.50, ACCENT, 2)
    fw, fh = record["fov_um_xy"]
    put(frame, f"{fw:g} x {fh:g} um", (1440, 282), 0.87, TEXT, 2)
    put(frame, "SAMPLING", (1440, 365), 0.50, ACCENT, 2)
    rx, ry = record["resolution_nm_xy"]
    put(frame, f"{rx:g} x {ry:g} nm/px", (1440, 417), 0.78, TEXT, 2)
    put(frame, "PHYSICAL BOUNDS", (1440, 500), 0.50, ACCENT, 2)
    x0, x1, y0, y1 = record["bounds_um_xyxy"]
    put(frame, f"x  {x0/1000:.3f}-{x1/1000:.3f} mm", (1440, 553), 0.66, TEXT, 2)
    put(frame, f"y  {y0/1000:.3f}-{y1/1000:.3f} mm", (1440, 595), 0.66, TEXT, 2)
    put(frame, "DISPLAY", (1440, 678), 0.50, ACCENT, 2)
    put(frame, "Raw electron microscopy", (1440, 730), 0.63, TEXT, 2)
    put(frame, "No whole-organ frame", (1440, 775), 0.63, MUTED, 2)
    local_box = (box[0], 156 + box[1], box[2], box[3])
    draw_scale_bar(frame, local_box, fw, 200 if fw >= 1000 else 20)
    header(frame, scope_label, record["label"], "Raw EM")
    footer(frame)
    return State(f"{prefix}.raw", f"{record['label']} - raw", frame, 1.65)


def mask_panel(raw, mask, record, key, label, bounds):
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0, y1 - y0
    background = gray_bgr(raw)
    visual = (background.astype(np.float32) * 0.20).astype(np.uint8)
    color = np.asarray(layer_color_bgr(record, key), np.uint8)
    visual[mask.astype(bool)] = color
    fitted, _ = fit_image(visual, width, height, background=(17, 22, 28))
    cv2.rectangle(fitted, (0, 0), (width - 1, height - 1), (58, 70, 82), 2)
    translucent_rect(fitted, (0, 0), (width, 92), color=(12, 16, 22), alpha=0.90)
    put(fitted, label, (30, 42), 0.80, TEXT, 2)
    density = record["layers"][key]["density_percent"]
    put(fitted, f"mask occupancy {density:.2f}%", (30, 76), 0.52, color.tolist(), 2)
    return fitted


def masks_state(prefix, raw, masks, record, scope_label):
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    panel_h = 430
    bounds = ((24, 156, 948, 156 + panel_h), (972, 156, 1896, 156 + panel_h),
              (24, 608, 948, 608 + panel_h), (972, 608, 1896, 608 + panel_h))
    for (key, label), panel_bounds in zip(LAYERS, bounds):
        x0, y0, x1, y1 = panel_bounds
        frame[y0:y1, x0:x1] = mask_panel(raw, masks[key], record, key, label, panel_bounds)
    header(frame, scope_label, record["label"], "Semantic masks | colored pixels are positive")
    footer(frame, "Four prediction layers | occupancy uses valid tissue pixels as denominator")
    return State(f"{prefix}.masks", f"{record['label']} - masks", frame, 1.70)


def legend_card(frame, record, x0=1420, y0=210):
    put(frame, "OVERLAY LEGEND", (x0, y0), 0.50, ACCENT, 2)
    for index, (key, label) in enumerate(LAYERS):
        y = y0 + 58 + index * 104
        color = layer_color_bgr(record, key)
        cv2.rectangle(frame, (x0, y - 25), (x0 + 34, y + 9), color, -1)
        put(frame, label, (x0 + 54, y), 0.63, TEXT, 2)
        density = record["layers"][key]["density_percent"]
        put(frame, f"{density:.2f}% of valid tissue", (x0 + 54, y + 34), 0.48, MUTED, 1)


def overlay_state(prefix, raw, masks, record, scope_label):
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    image, box = fit_image(overlay(raw, masks, record), 1370, 870)
    frame[156:1026, :1370] = image
    translucent_rect(frame, (1400, 174), (1884, 954), alpha=0.95)
    legend_card(frame, record)
    put(frame, "INTERPRETATION", (1420, 708), 0.50, ACCENT, 2)
    put(frame, "Raw structure remains visible", (1420, 758), 0.54, TEXT, 1)
    put(frame, "beneath transparent masks.", (1420, 796), 0.54, TEXT, 1)
    fw = record["fov_um_xy"][0]
    local_box = (box[0], 156 + box[1], box[2], box[3])
    draw_scale_bar(frame, local_box, fw, 200 if fw >= 1000 else 20)
    header(frame, scope_label, record["label"], "Combined segmentation overlay")
    footer(frame)
    return State(f"{prefix}.overlay", f"{record['label']} - overlay", frame, 1.80)


def density_visual(raw, density, vmax):
    heat = np.clip(density / max(vmax, 1e-6), 0.0, 1.0)
    heat_u8 = np.round(heat * 255).astype(np.uint8)
    heat_u8 = cv2.resize(heat_u8, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_CUBIC)
    colored = cv2.applyColorMap(heat_u8, cv2.COLORMAP_TURBO)
    background = gray_bgr(raw)
    alpha = np.where(heat_u8[..., None] > 2, 0.67, 0.22).astype(np.float32)
    return np.clip(background * (1.0 - alpha) + colored * alpha, 0, 255).astype(np.uint8)


def density_panel(raw, density, record, key, label, width, height):
    positive = density[density > 0]
    vmax = float(np.percentile(positive, 99)) if positive.size else 1.0
    vmax = max(vmax, float(record["layers"][key]["density_percent"]), 0.1)
    visual = density_visual(raw, density, vmax)
    fitted, _ = fit_image(visual, width, height, background=(17, 22, 28))
    translucent_rect(fitted, (0, 0), (width, 92), color=(12, 16, 22), alpha=0.90)
    put(fitted, label, (28, 42), 0.75, TEXT, 2)
    bin_um = record["layers"][key]["density_bin_um"]
    put(fitted, f"local density | {bin_um:g} um bins | scale 0-{vmax:.1f}%", (28, 76), 0.47, MUTED, 1)
    bar_x0, bar_x1, bar_y0, bar_y1 = width - 228, width - 28, 27, 48
    gradient = np.arange(256, dtype=np.uint8)[None, :]
    gradient = cv2.resize(gradient, (bar_x1 - bar_x0, bar_y1 - bar_y0))
    gradient = cv2.applyColorMap(gradient, cv2.COLORMAP_TURBO)
    fitted[bar_y0:bar_y1, bar_x0:bar_x1] = gradient
    cv2.rectangle(fitted, (bar_x0, bar_y0), (bar_x1, bar_y1), TEXT, 1)
    return fitted


def density_state(prefix, raw, densities, record, scope_label):
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    panel_w, panel_h = 924, 430
    origins = ((24, 156), (972, 156), (24, 608), (972, 608))
    for (key, label), (x, y) in zip(LAYERS, origins):
        panel = density_panel(raw, densities[key], record, key, label, panel_w, panel_h)
        frame[y:y + panel_h, x:x + panel_w] = panel
        cv2.rectangle(frame, (x, y), (x + panel_w - 1, y + panel_h - 1), (58, 70, 82), 2)
    header(frame, scope_label, record["label"], "Local structure-density maps")
    footer(frame, "Density = positive structure pixels / valid tissue pixels | display smoothing: sigma 0.8 bins")
    return State(f"{prefix}.density", f"{record['label']} - density", frame, 1.85)


def get_assets(npz, prefix):
    raw = npz[f"{prefix}_raw"]
    masks = {key: npz[f"{prefix}_mask_{key}"] for key, _ in LAYERS}
    densities = {key: npz[f"{prefix}_density_{key}"] for key, _ in LAYERS}
    return raw, masks, densities


def build_states(npz, manifest):
    states = []
    raw, masks, densities = get_assets(npz, "context")
    context = manifest["context"]
    for builder in (raw_state, masks_state, overlay_state, density_state):
        if builder is raw_state:
            states.append(builder("context", raw, context, "1 x 1 mm context ROI"))
        elif builder is masks_state or builder is overlay_state:
            states.append(builder("context", raw, masks, context, "1 x 1 mm context ROI"))
        else:
            states.append(builder("context", raw, densities, context, "1 x 1 mm context ROI"))
    for region in manifest["regions"]:
        prefix = f"detail_{region['id']}"
        raw, masks, densities = get_assets(npz, prefix)
        scope = "200 x 112.5 um detail ROI"
        states.extend((
            raw_state(prefix, raw, region, scope),
            masks_state(prefix, raw, masks, region, scope),
            overlay_state(prefix, raw, masks, region, scope),
            density_state(prefix, raw, densities, region, scope),
        ))
    return states


def crossfade(first, second, progress):
    alpha = smoothstep(progress)
    return cv2.addWeighted(first, 1.0 - alpha, second, alpha, 0)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_storyboard(states, output):
    thumb_w, thumb_h, columns = 480, 270, 4
    rows = int(np.ceil(len(states) / columns))
    sheet = np.full((rows * thumb_h, columns * thumb_w, 3), BG, np.uint8)
    for index, state in enumerate(states):
        thumb = cv2.resize(state.frame, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        row, col = divmod(index, columns)
        sheet[row * thumb_h:(row + 1) * thumb_h, col * thumb_w:(col + 1) * thumb_w] = thumb
    cv2.imwrite(str(output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])


def render(states, output):
    writer = imageio_ffmpeg.write_frames(
        str(output), (WIDTH, HEIGHT), fps=FPS, codec="libx264", quality=None,
        bitrate="3M", pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
        macro_block_size=8, ffmpeg_log_level="warning",
        output_params=["-movflags", "+faststart"],
    )
    writer.send(None)
    frame_count = 0
    timeline = []

    def emit(frame):
        nonlocal frame_count
        writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        frame_count += 1

    transition_frames = round(0.32 * FPS)
    for index, state in enumerate(states):
        if index:
            for step in range(transition_frames):
                emit(crossfade(states[index - 1].frame, state.frame, (step + 1) / transition_frames))
        first = frame_count
        for _ in range(round(state.hold_seconds * FPS)):
            emit(state.frame)
        timeline.append({"key": state.key, "title": state.title, "first_frame": first,
                         "last_frame": frame_count - 1, "mid_frame": (first + frame_count - 1) // 2})
    writer.close()
    return frame_count, timeline


def verify(video, expected_frames, timeline, manifest, output_dir):
    cap = cv2.VideoCapture(str(video))
    opened = bool(cap.isOpened())
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    selected = [item for item in timeline if item["key"].startswith("context.")]
    selected += [item for item in timeline if not item["key"].startswith("context.") and
                 item["key"].endswith((".masks", ".overlay", ".density"))]
    selected = selected[:16]
    decoded, thumbs = [], []
    for item in selected:
        cap.set(cv2.CAP_PROP_POS_FRAMES, item["mid_frame"])
        ok, frame = cap.read()
        decoded.append(bool(ok))
        thumbs.append(cv2.resize(frame, (480, 270)) if ok else np.zeros((270, 480, 3), np.uint8))
    cap.release()
    sheet = np.full((1080, 1920, 3), BG, np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, 4)
        sheet[row * 270:(row + 1) * 270, col * 480:(col + 1) * 480] = thumb
    contact = output_dir / "kidney-local-fields-tour-contact-sheet.jpg"
    cv2.imwrite(str(contact), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])

    required_suffixes = {".raw", ".masks", ".overlay", ".density"}
    timeline_keys = {item["key"] for item in timeline}
    checks = {
        "dimensions_1920x1080": (width, height) == (WIDTH, HEIGHT),
        "fps_24": abs(fps - FPS) < 0.05,
        "frame_count": count == expected_frames,
        "all_selected_keyframes_decoded": all(decoded),
        "one_1x1_mm_context": manifest["context"]["fov_um_xy"] == [1000.0, 1000.0],
        "four_detail_rois": len(manifest["regions"]) == 4,
        "all_story_stages_present": all(any(key.endswith(suffix) for key in timeline_keys)
                                          for suffix in required_suffixes),
        "four_masks_present": all(key in manifest["context"]["layers"] for key, _ in LAYERS),
    }
    report = {
        "video": Path(video).name,
        "opened": opened,
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": count,
        "duration_seconds": count / fps if fps else None,
        "sha256": sha256(video),
        "scope": "one 1 x 1 mm context ROI plus four 200 x 112.5 um detail ROIs; no whole-kidney frame",
        "layers": [label for _, label in LAYERS],
        "density_method": manifest["density_method"],
        "selected_keyframes": [item["key"] for item in selected],
        "checks": checks,
        "ok": opened and all(checks.values()),
        "timeline": timeline,
    }
    verification = output_dir / "kidney-local-fields-tour.verification.json"
    verification.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["ok"]:
        raise RuntimeError(f"video verification failed: {checks}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True,
                        help="NPZ produced by export_kidney_story_assets.py")
    parser.add_argument("--manifest", type=Path,
                        help="Defaults to <assets>.manifest.json")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("kidney-local-fields-tour.mp4"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest_path = args.manifest or args.assets.with_suffix(".manifest.json")
    if args.output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite {args.output}; use --force")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with np.load(args.assets) as npz:
        states = build_states(npz, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    storyboard = args.output.with_name("kidney-local-fields-tour-storyboard.jpg")
    write_storyboard(states, storyboard)
    frame_count, timeline = render(states, args.output)
    report = verify(args.output, frame_count, timeline, manifest, args.output.parent)
    print(json.dumps({"video": str(args.output), "storyboard": str(storyboard), **report}, indent=2))


if __name__ == "__main__":
    main()
