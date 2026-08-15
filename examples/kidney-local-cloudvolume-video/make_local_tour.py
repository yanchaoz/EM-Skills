#!/usr/bin/env python3
"""Render a 1 mm kidney segmentation/density story and random local tour.

The input is produced by ``export_kidney_story_assets.py``. Segmentation and
density are shown once at the large context scale. The camera then visibly
moves to four seeded-random 200 x 112.5 um local overlay views.
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
    render_fn: object | None = None


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


def state_frame(state, progress):
    return state.render_fn(progress) if state.render_fn is not None else state.frame


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
    source = gray_bgr(raw)
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    image, box = fit_image(source, 1370, 870)
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
    put(frame, "CAMERA", (1440, 678), 0.50, ACCENT, 2)
    put(frame, "Locked during review", (1440, 730), 0.60, TEXT, 1)
    put(frame, "No whole-organ frame", (1440, 775), 0.63, MUTED, 2)
    local_box = (box[0], 156 + box[1], box[2], box[3])
    draw_scale_bar(frame, local_box, fw, 200 if fw >= 1000 else 20)
    header(frame, scope_label, record["label"], "Raw EM | locked review hold")
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


def overlay_state(prefix, raw, masks, record, scope_label, hold_seconds=1.80):
    source = overlay(raw, masks, record)
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    image, box = fit_image(source, 1370, 870)
    frame[156:1026, :1370] = image
    translucent_rect(frame, (1400, 174), (1884, 954), alpha=0.95)
    legend_card(frame, record)
    put(frame, "INTERPRETATION", (1420, 708), 0.50, ACCENT, 2)
    put(frame, "One transform preserves", (1420, 758), 0.54, TEXT, 1)
    put(frame, "raw-mask alignment.", (1420, 796), 0.54, TEXT, 1)
    put(frame, "Hold remains pixel-stable.", (1420, 850), 0.50, MUTED, 1)
    fw = record["fov_um_xy"][0]
    local_box = (box[0], 156 + box[1], box[2], box[3])
    draw_scale_bar(frame, local_box, fw, 200 if fw >= 1000 else 20)
    header(frame, scope_label, record["label"], "Combined overlay | locked review hold")
    footer(frame)
    return State(f"{prefix}.overlay", f"{record['label']} - overlay", frame, hold_seconds)


def context_camera_frame(source, context, center_nm, fov_um_x):
    """Crop a physical 16:9 camera view from the aligned 1 mm context overlay."""
    x0, x1, y0, y1 = context["bounds_um_xyxy"]
    cx, cy = center_nm[0] / 1000.0, center_nm[1] / 1000.0
    fov_x = min(float(fov_um_x), x1 - x0)
    fov_y = min(fov_x * HEIGHT / WIDTH, y1 - y0)
    cx = float(np.clip(cx, x0 + fov_x / 2, x1 - fov_x / 2))
    cy = float(np.clip(cy, y0 + fov_y / 2, y1 - fov_y / 2))
    sx0 = int(np.floor((cx - fov_x / 2 - x0) / (x1 - x0) * source.shape[1]))
    sx1 = int(np.ceil((cx + fov_x / 2 - x0) / (x1 - x0) * source.shape[1]))
    sy0 = int(np.floor((cy - fov_y / 2 - y0) / (y1 - y0) * source.shape[0]))
    sy1 = int(np.ceil((cy + fov_y / 2 - y0) / (y1 - y0) * source.shape[0]))
    crop = source[max(0, sy0):min(source.shape[0], sy1), max(0, sx0):min(source.shape[1], sx1)]
    if not crop.size:
        raise RuntimeError("Camera crop is empty")
    return cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC), fov_x


def move_state(index, context_source, context, start_center, end_center, first_move=False):
    seed = int(context["local_stop_selection"]["seed"])

    def make_frame(progress):
        u = smoothstep(progress)
        center = [start_center[axis] * (1.0 - u) + end_center[axis] * u for axis in range(2)]
        if first_move:
            fov_x = 900.0 * (1.0 - u) + 200.0 * u
        else:
            fov_x = 200.0 * (1.0 + 0.72 * 4.0 * u * (1.0 - u))
        frame, actual_fov = context_camera_frame(context_source, context, center, fov_x)
        header(frame, "SEEDED-RANDOM LOCAL TOUR", f"Camera move to local view {index}",
               f"seed {seed} | selection order {index}/4")
        footer(frame, "Movement is interpolated in physical coordinates inside the 1 x 1 mm context ROI")
        draw_scale_bar(frame, (0, 142, WIDTH, HEIGHT - 196), actual_fov, 100 if actual_fov >= 500 else 20)
        return frame

    return State(f"random-{index:02d}.move", f"Move to random local view {index}",
                 make_frame(0.5), 2.40, make_frame)


def density_visual(raw, density, vmax):
    heat = np.clip(density / max(vmax, 1e-6), 0.0, 1.0)
    heat_u8 = np.round(heat * 255).astype(np.uint8)
    heat_u8 = cv2.resize(heat_u8, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_CUBIC)
    colored = cv2.applyColorMap(heat_u8, cv2.COLORMAP_TURBO)
    background = gray_bgr(raw)
    alpha = np.where(heat_u8[..., None] > 2, 0.67, 0.22).astype(np.float32)
    return np.clip(background * (1.0 - alpha) + colored * alpha, 0, 255).astype(np.uint8)


def density_state(prefix, raw, density, record, key, label, scope_label):
    positive = density[density > 0]
    vmax = float(np.percentile(positive, 99)) if positive.size else 1.0
    vmax = max(vmax, float(record["layers"][key]["density_percent"]), 0.1)
    frame = np.full((HEIGHT, WIDTH, 3), BG, np.uint8)
    image, box = fit_image(density_visual(raw, density, vmax), 1370, 870,
                           background=(17, 22, 28))
    frame[156:1026, :1370] = image
    translucent_rect(frame, (1400, 174), (1884, 954), alpha=0.95)
    color = layer_color_bgr(record, key)
    cv2.rectangle(frame, (1430, 212), (1472, 254), color, -1)
    put(frame, label, (1490, 248), 0.72, TEXT, 2)
    put(frame, "CONTEXT OCCUPANCY", (1430, 342), 0.48, ACCENT, 2)
    occupancy = float(record["layers"][key]["density_percent"])
    put(frame, f"{occupancy:.2f}%", (1430, 400), 0.92, TEXT, 2)
    put(frame, "DENSITY GRID", (1430, 500), 0.48, ACCENT, 2)
    bin_um = record["layers"][key]["density_bin_um"]
    put(frame, f"{bin_um:g} um physical bins", (1430, 548), 0.58, TEXT, 1)
    put(frame, "DISPLAY RANGE", (1430, 644), 0.48, ACCENT, 2)
    put(frame, f"0-{vmax:.1f}%", (1430, 694), 0.66, TEXT, 2)
    bar_x0, bar_x1, bar_y0, bar_y1 = 1430, 1830, 730, 760
    gradient = np.arange(256, dtype=np.uint8)[None, :]
    gradient = cv2.resize(gradient, (bar_x1 - bar_x0, bar_y1 - bar_y0))
    gradient = cv2.applyColorMap(gradient, cv2.COLORMAP_TURBO)
    frame[bar_y0:bar_y1, bar_x0:bar_x1] = gradient
    cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), TEXT, 1)
    fw = record["fov_um_xy"][0]
    local_box = (box[0], 156 + box[1], box[2], box[3])
    draw_scale_bar(frame, local_box, fw, 200 if fw >= 1000 else 20)
    header(frame, scope_label, f"{label} density",
           "Full-size context map | locked review hold")
    footer(frame, "Density = positive structure pixels / valid tissue pixels | display smoothing: sigma 0.8 bins")
    return State(f"{prefix}.density.{key}", f"{record['label']} - {label} density",
                 frame, 2.10)


def get_assets(npz, prefix):
    raw = npz[f"{prefix}_raw"]
    masks = {key: npz[f"{prefix}_mask_{key}"] for key, _ in LAYERS}
    densities = {key: npz[f"{prefix}_density_{key}"] for key, _ in LAYERS}
    return raw, masks, densities


def build_states(npz, manifest):
    states = []
    raw, masks, densities = get_assets(npz, "context")
    context = manifest["context"]
    states.append(raw_state("context", raw, context, "1 x 1 mm context ROI"))
    states.append(masks_state("context", raw, masks, context, "1 x 1 mm context ROI"))
    states.append(overlay_state("context", raw, masks, context, "1 x 1 mm context ROI"))
    for key, label in LAYERS:
        states.append(density_state("context", raw, densities[key], context, key,
                                    label, "1 x 1 mm context ROI"))
    context["local_stop_selection"] = manifest["local_stop_selection"]
    context_overlay = overlay(raw, masks, context)
    previous_center = context["center_nm_xy"]
    for index, region in enumerate(manifest["regions"], 1):
        prefix = f"detail_{region['id']}"
        detail_raw, detail_masks, _ = get_assets(npz, prefix)
        states.append(move_state(index, context_overlay, context, previous_center,
                                 region["center_nm_xy"], first_move=index == 1))
        states.append(overlay_state(prefix, detail_raw, detail_masks, region,
                                    "Seeded-random 200 x 112.5 um local ROI", 2.55))
        previous_center = region["center_nm_xy"]
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
        thumb = cv2.resize(state_frame(state, 0.5), (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        row, col = divmod(index, columns)
        sheet[row * thumb_h:(row + 1) * thumb_h, col * thumb_w:(col + 1) * thumb_w] = thumb
    cv2.imwrite(str(output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])


def write_density_comparison(manifest, output):
    """Summarize occupancy in the four random local fields without anatomy claims."""
    width, height = 1600, 900
    frame = np.full((height, width, 3), BG, np.uint8)
    put(frame, "Seeded-random local occupancy", (54, 72), 1.25, TEXT, 3)
    seed = manifest["local_stop_selection"]["seed"]
    put(frame, f"Four local views inside the 1 x 1 mm context | seed {seed}",
        (56, 116), 0.62, MUTED, 1)
    values = [region["layers"][key]["density_percent"]
              for region in manifest["regions"] for key, _ in LAYERS]
    vmax = max(values + [1.0]) * 1.12
    chart_x0, chart_x1 = 520, 1510
    for row, region in enumerate(manifest["regions"]):
        y0 = 170 + row * 170
        put(frame, region["label"], (56, y0 + 30), 0.72, TEXT, 2)
        cx, cy = region["center_nm_xy"]
        put(frame, f"center ({cx/1000:.1f}, {cy/1000:.1f}) um",
            (56, y0 + 66), 0.48, MUTED, 1)
        for index, (key, label) in enumerate(LAYERS):
            y = y0 + index * 29
            value = float(region["layers"][key]["density_percent"])
            color = layer_color_bgr(region, key)
            bar_end = chart_x0 + round((chart_x1 - chart_x0) * value / vmax)
            cv2.rectangle(frame, (chart_x0, y + 2), (chart_x1, y + 18), (35, 43, 52), -1)
            cv2.rectangle(frame, (chart_x0, y + 2), (bar_end, y + 18), color, -1)
            put(frame, label, (300, y + 17), 0.42, MUTED, 1)
            put(frame, f"{value:.2f}%", (min(chart_x1 - 72, bar_end + 10), y + 17), 0.42, TEXT, 1)
        cv2.line(frame, (54, y0 + 145), (1546, y0 + 145), (48, 58, 68), 1)
    put(frame, "Occupancy = positive mask pixels / valid tissue pixels", (56, 866), 0.50, MUTED, 1)
    cv2.imwrite(str(output), frame, [cv2.IMWRITE_PNG_COMPRESSION, 3])


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
    previous_final = None
    for index, state in enumerate(states):
        if index:
            current_start = state_frame(state, 0.0)
            for step in range(transition_frames):
                emit(crossfade(previous_final, current_start, (step + 1) / transition_frames))
        first = frame_count
        hold_frames = round(state.hold_seconds * FPS)
        for step in range(hold_frames):
            emit(state_frame(state, step / max(1, hold_frames - 1)))
        previous_final = state_frame(state, 1.0)
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
    selected = list(timeline)
    decoded, thumbs = [], []
    for item in selected:
        cap.set(cv2.CAP_PROP_POS_FRAMES, item["mid_frame"])
        ok, frame = cap.read()
        decoded.append(bool(ok))
        thumbs.append(cv2.resize(frame, (480, 270)) if ok else np.zeros((270, 480, 3), np.uint8))
    motion_differences = {}
    static_hold_differences = {}
    static_hold_shifts_px = {}
    motion_rows = []
    motion_sheet_keys = {"random-01.move", "random-02.move", "random-03.move", "random-04.move"}
    for item in timeline:
        cap.set(cv2.CAP_PROP_POS_FRAMES, item["first_frame"])
        ok0, first = cap.read()
        cap.set(cv2.CAP_PROP_POS_FRAMES, item["mid_frame"])
        okm, middle = cap.read()
        cap.set(cv2.CAP_PROP_POS_FRAMES, item["last_frame"])
        ok1, last = cap.read()
        if item["key"].endswith(".move"):
            motion_differences[item["key"]] = (
                float(np.mean(np.abs(first.astype(np.float32) - last.astype(np.float32))))
                if ok0 and ok1 else 0.0
            )
            if item["key"] in motion_sheet_keys and ok0 and okm and ok1:
                motion_rows.append((first, middle, last))
        elif ok0 and okm and ok1:
            static_hold_differences[item["key"]] = max(
                float(np.mean(np.abs(first.astype(np.float32) - middle.astype(np.float32)))),
                float(np.mean(np.abs(middle.astype(np.float32) - last.astype(np.float32)))),
            )
            gray = [cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32),
                                     (0, 0), 2.0)
                    for frame in (first, middle, last)]
            shifts = [cv2.phaseCorrelate(a, b)[0]
                      for a, b in ((gray[0], gray[1]), (gray[1], gray[2]))]
            static_hold_shifts_px[item["key"]] = [
                [float(shift[0]), float(shift[1])] for shift in shifts
            ]
    cap.release()
    motion_sheet = np.full((len(motion_rows) * 360, 1920, 3), BG, np.uint8)
    for row, frames in enumerate(motion_rows):
        for col, frame in enumerate(frames):
            motion_sheet[row * 360:(row + 1) * 360, col * 640:(col + 1) * 640] = cv2.resize(
                frame, (640, 360), interpolation=cv2.INTER_AREA
            )
    motion_contact = output_dir / "kidney-local-fields-tour-motion-contact-sheet.jpg"
    cv2.imwrite(str(motion_contact), motion_sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    contact_rows = int(np.ceil(len(thumbs) / 4))
    sheet = np.full((contact_rows * 270, 1920, 3), BG, np.uint8)
    for index, thumb in enumerate(thumbs):
        row, col = divmod(index, 4)
        sheet[row * 270:(row + 1) * 270, col * 480:(col + 1) * 480] = thumb
    contact = output_dir / "kidney-local-fields-tour-contact-sheet.jpg"
    cv2.imwrite(str(contact), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])

    timeline_keys = {item["key"] for item in timeline}
    timeline_order = [item["key"] for item in timeline]
    context_bounds = manifest["context"]["bounds_um_xyxy"]
    random_centers_inside = all(
        context_bounds[0] <= region["center_nm_xy"][0] / 1000 <= context_bounds[1] and
        context_bounds[2] <= region["center_nm_xy"][1] / 1000 <= context_bounds[3]
        for region in manifest["regions"]
    )
    move_keys = [key for key in timeline_keys if key.endswith(".move")]
    density_keys = [f"context.density.{key}" for key, _ in LAYERS]
    density_indices = [timeline_order.index(key) for key in density_keys
                       if key in timeline_keys]
    context_overlay_index = timeline_order.index("context.overlay")
    first_move_index = timeline_order.index("random-01.move")
    density_sequence_ok = (
        len(density_indices) == len(LAYERS) and
        context_overlay_index < min(density_indices) and
        max(density_indices) < first_move_index
    )
    checks = {
        "dimensions_1920x1080": (width, height) == (WIDTH, HEIGHT),
        "fps_24": abs(fps - FPS) < 0.05,
        "frame_count": count == expected_frames,
        "all_selected_keyframes_decoded": all(decoded),
        "one_1x1_mm_context": manifest["context"]["fov_um_xy"] == [1000.0, 1000.0],
        "four_full_size_context_density_holds": (
            all(key in timeline_keys for key in density_keys) and density_sequence_ok
        ),
        "four_seeded_random_detail_rois": (
            len(manifest["regions"]) == 4 and
            manifest["local_stop_selection"]["mode"] == "seeded_random" and
            isinstance(manifest["local_stop_selection"]["seed"], int)
        ),
        "random_centers_inside_context": random_centers_inside,
        "no_invented_anatomical_region_names": all(
            region["label"].startswith("Random local view") for region in manifest["regions"]),
        "four_visible_camera_moves": len(move_keys) == 4,
        "four_masks_present": all(key in manifest["context"]["layers"] for key, _ in LAYERS),
        "smooth_camera_motion_present": bool(motion_differences) and
                                          all(value > 0.5 for value in motion_differences.values()),
        "all_global_and_local_holds_geometrically_locked": bool(static_hold_shifts_px) and all(
            max(abs(axis) for shift in shifts for axis in shift) <= 0.15
            for shifts in static_hold_shifts_px.values()
        ),
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
        "scope": "1 x 1 mm segmentation/density context followed by four seeded-random 200 x 112.5 um local views",
        "layers": [label for _, label in LAYERS],
        "density_method": manifest["density_method"],
        "camera_motion": {
            "easing": "smoothstep", "first_move_fov_um": "900 -> 200",
            "between_view_midpoint_zoom_out_percent": 72,
            "local_hold_push_in_percent": 0.0,
            "pan_fraction_of_frame": 0.0,
            "applied_to": "aligned combined-overlay composites",
            "motion_mean_absolute_frame_differences": motion_differences,
            "static_hold_mean_absolute_frame_differences": static_hold_differences,
            "static_hold_phase_correlation_shifts_px": static_hold_shifts_px,
            "static_hold_shift_tolerance_px": 0.15,
        },
        "local_stop_selection": manifest["local_stop_selection"],
        "local_views": [{
            "id": region["id"], "label": region["label"],
            "center_nm_xy": region["center_nm_xy"],
            "bounds_um_xyxy": region["bounds_um_xyxy"],
            "selection_candidate_index": region["selection_candidate_index"],
            "selection_tissue_fraction": region["selection_tissue_fraction"],
        } for region in manifest["regions"]],
        "source_info_sha256": {
            dataset: record["info_sha256"] for dataset, record in manifest["sources"].items()
        },
        "selected_keyframes": [item["key"] for item in selected],
        "motion_contact_sheet": motion_contact.name,
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
    write_density_comparison(manifest, args.output.with_name("local-region-density-comparison.png"))
    storyboard = args.output.with_name("kidney-local-fields-tour-storyboard.jpg")
    write_storyboard(states, storyboard)
    frame_count, timeline = render(states, args.output)
    report = verify(args.output, frame_count, timeline, manifest, args.output.parent)
    print(json.dumps({"video": str(args.output), "storyboard": str(storyboard), **report}, indent=2))


if __name__ == "__main__":
    main()
