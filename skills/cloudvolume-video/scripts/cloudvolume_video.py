#!/usr/bin/env python3
"""Config-driven CloudVolume scientific video pipeline.

Dependencies on the execution host: cloud-volume, numpy, opencv-python.
The script is intentionally self-contained so it can be copied to a data server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from urllib.parse import quote


DEFAULT_CAMERA = {
    "easing": "smootherstep",
    "entry_start_fov_multiplier": 1.40,
    "hold_pan_fraction": 0.035,
    "hold_zoom_fraction": 0.06,
    "transition_zoom_out_fraction": 0.16,
}


DEFAULT_VIDEO = {
    "width": 1920, "height": 1080, "fps": 30,
    "preview_resolution_nm": 640, "detail_resolution_nm": 160,
    "detail_fov_um": 200.0, "detail_scale_bar_um": 10.0,
    "overview_scale_bar_um": 1000.0, "density_bin_um": 10.24,
    "density_display_quantile": 0.99,
    "metadata_seconds": 3.0, "isolated_seconds": 2.5,
    "density_seconds": 2.5, "all_seconds": 3.0,
    "zoom_seconds": 4.0, "hold_seconds": 3.0, "move_seconds": 3.0,
    "fade_frames": 15, "png_frames": True, "png_compression": 2,
    "codec": "mp4v", "bulk_missing_mip_max_gb": 64.0,
    "source_tile_max_pixels": 4096,
    "tissue": {"min_intensity": 1, "max_intensity": 249},
    "camera": DEFAULT_CAMERA,
}


def deps():
    try:
        import cv2
        import numpy as np
        from cloudvolume import CloudVolume
    except ImportError as e:
        raise SystemExit(
            "Missing runtime dependency. Install cloud-volume, numpy, and opencv-python "
            f"in the execution environment: {e}"
        )
    return cv2, np, CloudVolume


def load_config(path: Path):
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["video"] = {**DEFAULT_VIDEO, **cfg.get("video", {})}
    cfg["video"]["tissue"] = {
        **DEFAULT_VIDEO["tissue"], **cfg["video"].get("tissue", {})
    }
    cfg["video"]["camera"] = {
        **DEFAULT_CAMERA, **cfg["video"].get("camera", {})
    }
    required = ["project_name", "source_root", "output_root", "specimens"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing config keys: {missing}")
    if Path(cfg["source_root"]).resolve() == Path(cfg["output_root"]).resolve():
        raise ValueError("source_root and output_root must differ")
    ids = [x["id"] for x in cfg["specimens"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Specimen ids must be unique")
    video = cfg["video"]
    for key in ("metadata_seconds", "isolated_seconds", "density_seconds", "all_seconds",
                "zoom_seconds", "hold_seconds", "move_seconds"):
        if float(video[key]) < 0:
            raise ValueError(f"video.{key} must be non-negative")
    if int(video["fps"]) <= 0 or int(video["width"]) <= 0 or int(video["height"]) <= 0:
        raise ValueError("video width, height, and fps must be positive")
    camera = video["camera"]
    if camera["easing"] not in {"linear", "smoothstep", "smootherstep", "cosine"}:
        raise ValueError("video.camera.easing must be linear, smoothstep, smootherstep, or cosine")
    if float(camera["entry_start_fov_multiplier"]) < 1.0:
        raise ValueError("video.camera.entry_start_fov_multiplier must be >= 1")
    for key, upper in (("hold_pan_fraction", 0.20), ("hold_zoom_fraction", 0.35),
                       ("transition_zoom_out_fraction", 1.0)):
        value = float(camera[key])
        if not 0.0 <= value <= upper:
            raise ValueError(f"video.camera.{key} must be in [0, {upper}]")
    for specimen in cfg["specimens"]:
        if not specimen.get("layers"):
            raise ValueError(f"{specimen['id']} has no layers")
        for layer in specimen["layers"]:
            rgb = layer.get("color_rgb")
            if not (isinstance(rgb, list) and len(rgb) == 3 and all(0 <= x <= 255 for x in rgb)):
                raise ValueError(f"Invalid color_rgb in {specimen['id']}/{layer.get('id')}")
            if not 0 <= float(layer.get("opacity", 0.6)) <= 1:
                raise ValueError(f"Invalid opacity in {specimen['id']}/{layer.get('id')}")
        story = specimen.get("story", {})
        roi = story.get("context_roi_um_xyxy")
        if roi is not None and not (
                isinstance(roi, list) and len(roi) == 4 and
                all(isinstance(value, (int, float)) for value in roi) and
                roi[0] < roi[1] and roi[2] < roi[3]):
            raise ValueError(f"Invalid story.context_roi_um_xyxy in {specimen['id']}")
        selection = story.get("local_stops", {})
        if selection:
            mode = selection.get("mode", "representative")
            if mode not in {"representative", "seeded_random"}:
                raise ValueError(f"Invalid story.local_stops.mode in {specimen['id']}")
            if int(selection.get("count", 4)) <= 0:
                raise ValueError(f"story.local_stops.count must be positive in {specimen['id']}")
            if mode == "seeded_random" and not isinstance(selection.get("seed"), int):
                raise ValueError(f"seeded_random requires an integer seed in {specimen['id']}")
    return cfg


def smoothstep(x):
    x = max(0.0, min(1.0, float(x)))
    return x * x * (3 - 2 * x)


def ease(x):
    x = max(0.0, min(1.0, float(x)))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def easing_value(name, x):
    """Return a clamped deterministic interpolation weight."""
    x = max(0.0, min(1.0, float(x)))
    if name == "linear":
        return x
    if name == "smoothstep":
        return x * x * (3.0 - 2.0 * x)
    if name == "smootherstep":
        return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)
    if name == "cosine":
        return 0.5 - 0.5 * math.cos(math.pi * x)
    raise ValueError(f"Unknown camera easing: {name}")


def _hold_pose(stops, index, progress, base_fov_nm, camera):
    """Create a continuous slow push-in plus restrained pan for one hold."""
    u = easing_value(camera["easing"], progress)
    directions = ((1.0, -0.36), (-0.72, 0.62), (0.45, 0.82), (-1.0, -0.28))
    dx, dy = directions[index % len(directions)]
    norm = math.hypot(dx, dy)
    amplitude = float(camera["hold_pan_fraction"]) * base_fov_nm / 2.0
    offset = (amplitude * dx / norm, amplitude * dy / norm)
    center = (stops[index][0] + (2.0 * u - 1.0) * offset[0],
              stops[index][1] + (2.0 * u - 1.0) * offset[1])
    fov = base_fov_nm * (1.0 + float(camera["hold_zoom_fraction"]) * (1.0 - u))
    return center, fov


def camera_pose(t, stops, base_fov_nm, zoom_seconds, hold_seconds, move_seconds,
                include_overview, camera, entry_center=None):
    """Return center, physical FOV, stop index, and phase for a camera time."""
    if not stops:
        raise ValueError("Camera tour requires at least one stop")
    t = max(0.0, float(t))
    zoom = float(zoom_seconds) if include_overview else 0.0
    hold, move = float(hold_seconds), float(move_seconds)
    first_center, first_fov = _hold_pose(stops, 0, 0.0, base_fov_nm, camera)
    if zoom > 0.0 and t < zoom:
        u = easing_value(camera["easing"], t / zoom)
        start_fov = base_fov_nm * float(camera["entry_start_fov_multiplier"])
        source_center = tuple(entry_center) if entry_center is not None else first_center
        center = tuple(source_center[index] * (1.0 - u) + first_center[index] * u
                       for index in range(2))
        return {
            "center": center,
            "fov_nm": start_fov * (1.0 - u) + first_fov * u,
            "stop_index": None,
            "phase": "entry_zoom",
            "progress": u,
        }

    tt = t - zoom
    cursor = 0.0
    for index in range(len(stops)):
        if hold > 0.0 and tt < cursor + hold:
            u = (tt - cursor) / hold
            center, fov = _hold_pose(stops, index, u, base_fov_nm, camera)
            return {"center": center, "fov_nm": fov, "stop_index": index,
                    "phase": "hold", "progress": easing_value(camera["easing"], u)}
        cursor += hold
        if index >= len(stops) - 1:
            break
        if move > 0.0 and tt < cursor + move:
            u = easing_value(camera["easing"], (tt - cursor) / move)
            start_center, start_fov = _hold_pose(stops, index, 1.0, base_fov_nm, camera)
            end_center, end_fov = _hold_pose(stops, index + 1, 0.0, base_fov_nm, camera)
            center = tuple(start_center[j] * (1.0 - u) + end_center[j] * u for j in range(2))
            base_fov = start_fov * (1.0 - u) + end_fov * u
            zoom_out = 4.0 * u * (1.0 - u) * float(camera["transition_zoom_out_fraction"])
            return {"center": center, "fov_nm": base_fov * (1.0 + zoom_out),
                    "stop_index": None, "phase": "move", "progress": u}
        cursor += move

    center, fov = _hold_pose(stops, len(stops) - 1, 1.0, base_fov_nm, camera)
    return {"center": center, "fov_nm": fov, "stop_index": len(stops) - 1,
            "phase": "hold", "progress": 1.0}


class Pipeline:
    def __init__(self, config_path: Path):
        self.config_path = config_path.resolve()
        self.cfg = load_config(self.config_path)
        self.v = self.cfg["video"]
        self.W, self.H, self.FPS = int(self.v["width"]), int(self.v["height"]), int(self.v["fps"])
        self.source_root = Path(self.cfg["source_root"])
        self.output_root = Path(self.cfg["output_root"])
        self.cv2, self.np, self.CloudVolume = deps()

    def specimens(self, selected):
        wanted = set(selected or [])
        result = [x for x in self.cfg["specimens"] if not wanted or x["id"] in wanted]
        missing = wanted - {x["id"] for x in result}
        if missing:
            raise ValueError(f"Unknown specimen ids: {sorted(missing)}")
        return result

    def dataset_path(self, dataset):
        p = Path(dataset)
        return p if p.is_absolute() else self.source_root / p

    def volume(self, dataset):
        p = self.dataset_path(dataset)
        if not p.exists():
            raise FileNotFoundError(p)
        return self.CloudVolume("file://" + str(p), progress=False, fill_missing=True)

    @staticmethod
    def mip_pairs(cv):
        return [(int(m), int(cv.mip_resolution(m)[0])) for m in cv.available_mips]

    def native_meta(self, dataset):
        cv = self.volume(dataset)
        mip = min(cv.available_mips)
        cv.mip = mip
        b = cv.bounds
        res = tuple(map(int, cv.mip_resolution(mip)[:2]))
        size = (int(b.maxpt[0] - b.minpt[0]), int(b.maxpt[1] - b.minpt[1]))
        origin_nm = (int(b.minpt[0]) * res[0], int(b.minpt[1]) * res[1])
        return {
            "mip": int(mip), "resolution_nm": list(res), "size_xy": list(size),
            "origin_nm": list(origin_nm), "dtype": str(cv.dtype),
            "available_mips": [m for m, _ in self.mip_pairs(cv)],
            "mip_resolutions_nm": [r for _, r in self.mip_pairs(cv)],
            "physical_size_nm": [size[0] * res[0], size[1] * res[1]],
        }

    def _read_query(self, cv, x0, x1, y0, y1):
        a = self.np.asarray(cv[int(x0):int(x1), int(y0):int(y1), 0:1]).squeeze()
        if a.ndim != 2:
            a = self.np.reshape(a, (int(x1 - x0), int(y1 - y0)))
        return a.T

    def _resize_data(self, a, width, height, categorical, source_res, target_res):
        """Resize raw images with OpenCV and labels with dtype-safe nearest sampling."""
        if categorical:
            yi = self.np.minimum((self.np.arange(height) * a.shape[0] / height).astype(self.np.int64), a.shape[0] - 1)
            xi = self.np.minimum((self.np.arange(width) * a.shape[1] / width).astype(self.np.int64), a.shape[1] - 1)
            return a[yi[:, None], xi[None, :]]
        interpolation = self.cv2.INTER_AREA if source_res < target_res else self.cv2.INTER_LINEAR
        return self.cv2.resize(a, (width, height), interpolation=interpolation)

    def read_aligned(self, dataset, target_res_nm, x0, x1, y0, y1, raw_origin_nm,
                     categorical=True, allow_bulk=False):
        """Read onto a grid relative to raw_origin_nm; bounds are target-grid pixels."""
        cv = self.volume(dataset)
        pairs = self.mip_pairs(cv)
        exact = [m for m, r in pairs if r == int(target_res_nm)]
        if exact:
            mip, source_res = exact[0], int(target_res_nm)
        else:
            mip, source_res = min(pairs, key=lambda mr: abs(math.log(mr[1] / target_res_nm)))
        cv.mip = mip
        b = cv.bounds
        out_w, out_h = int(x1 - x0), int(y1 - y0)
        out = self.np.zeros((out_h, out_w), dtype=self.np.dtype(cv.dtype))
        if out_w <= 0 or out_h <= 0:
            return out

        world_x0 = raw_origin_nm[0] + x0 * target_res_nm
        world_y0 = raw_origin_nm[1] + y0 * target_res_nm
        source_world = (
            int(b.minpt[0]) * source_res, int(b.maxpt[0]) * source_res,
            int(b.minpt[1]) * source_res, int(b.maxpt[1]) * source_res,
        )
        full_bytes = ((int(b.maxpt[0]) - int(b.minpt[0])) *
                      (int(b.maxpt[1]) - int(b.minpt[1])) * self.np.dtype(cv.dtype).itemsize)
        bulk_limit = float(self.v["bulk_missing_mip_max_gb"]) * (1024 ** 3)
        covers_origin = x0 == 0 and y0 == 0
        if allow_bulk and covers_origin and bulk_limit > 0 and full_bytes <= bulk_limit:
            print(f"BULK_READ dataset={dataset} mip={mip} res_nm={source_res} bytes={full_bytes}", flush=True)
            a = self._read_query(cv, b.minpt[0], b.maxpt[0], b.minpt[1], b.maxpt[1])
            return self._resize_data(a, out_w, out_h, categorical, source_res, target_res_nm)

        max_source = int(self.v["source_tile_max_pixels"])
        tile = max(16, min(1024, int(max_source * source_res / target_res_nm)))
        total = math.ceil(out_w / tile) * math.ceil(out_h / tile)
        done = 0; next_report = 0.1
        for oy0 in range(0, out_h, tile):
            oy1 = min(out_h, oy0 + tile)
            for ox0 in range(0, out_w, tile):
                ox1 = min(out_w, ox0 + tile)
                wx0 = world_x0 + ox0 * target_res_nm; wx1 = world_x0 + ox1 * target_res_nm
                wy0 = world_y0 + oy0 * target_res_nm; wy1 = world_y0 + oy1 * target_res_nm
                ix0, ix1 = max(wx0, source_world[0]), min(wx1, source_world[1])
                iy0, iy1 = max(wy0, source_world[2]), min(wy1, source_world[3])
                if ix1 > ix0 and iy1 > iy0:
                    dx0 = max(0, int(round((ix0 - wx0) / target_res_nm)))
                    dx1 = min(ox1 - ox0, int(round((ix1 - wx0) / target_res_nm)))
                    dy0 = max(0, int(round((iy0 - wy0) / target_res_nm)))
                    dy1 = min(oy1 - oy0, int(round((iy1 - wy0) / target_res_nm)))
                    sx0 = max(int(b.minpt[0]), int(math.floor(ix0 / source_res)))
                    sx1 = min(int(b.maxpt[0]), int(math.ceil(ix1 / source_res)))
                    sy0 = max(int(b.minpt[1]), int(math.floor(iy0 / source_res)))
                    sy1 = min(int(b.maxpt[1]), int(math.ceil(iy1 / source_res)))
                    if sx1 > sx0 and sy1 > sy0 and dx1 > dx0 and dy1 > dy0:
                        a = self._read_query(cv, sx0, sx1, sy0, sy1)
                        out[oy0 + dy0:oy0 + dy1, ox0 + dx0:ox0 + dx1] = self._resize_data(
                            a, dx1 - dx0, dy1 - dy0, categorical, source_res, target_res_nm)
                done += 1
                if total >= 20 and done / total >= next_report:
                    print(f"TILED_READ dataset={dataset} {done}/{total}", flush=True)
                    next_report += 0.1
        return out

    def label_mask(self, a, value):
        if value is None:
            return a != 0
        if isinstance(value, list):
            return self.np.isin(a, value)
        return a == value

    def read_preview(self, specimen):
        native = self.native_meta(specimen["raw"])
        target = int(self.v["preview_resolution_nm"])
        source_physical = tuple(native["physical_size_nm"])
        roi = specimen.get("story", {}).get("context_roi_um_xyxy")
        if roi is None:
            bounds_nm = (0.0, source_physical[0], 0.0, source_physical[1])
        else:
            bounds_nm = tuple(float(value) * 1000.0 for value in roi)
            if not (0 <= bounds_nm[0] < bounds_nm[1] <= source_physical[0] and
                    0 <= bounds_nm[2] < bounds_nm[3] <= source_physical[1]):
                raise ValueError(f"Context ROI is outside raw bounds for {specimen['id']}: {roi}")
        x0 = int(math.floor(bounds_nm[0] / target)); x1 = int(math.ceil(bounds_nm[1] / target))
        y0 = int(math.floor(bounds_nm[2] / target)); y1 = int(math.ceil(bounds_nm[3] / target))
        w, h = x1 - x0, y1 - y0
        origin = tuple(native["origin_nm"])
        raw = self.read_aligned(specimen["raw"], target, x0, x1, y0, y1, origin,
                                categorical=False, allow_bulk=True).astype(self.np.uint8)
        masks = {}; cache = {}
        for layer in specimen["layers"]:
            ds = layer["dataset"]
            if ds not in cache:
                cache[ds] = self.read_aligned(ds, target, x0, x1, y0, y1, origin,
                                              categorical=True, allow_bulk=True)
            masks[layer["id"]] = self.label_mask(cache[ds], layer.get("label_value"))
        context_size = [w * target, h * target]
        meta = {**native, "source_size_xy": native["size_xy"],
                "source_physical_size_nm": list(source_physical),
                "size_xy": [int(math.ceil(context_size[0] / native["resolution_nm"][0])),
                            int(math.ceil(context_size[1] / native["resolution_nm"][1]))],
                "physical_size_nm": context_size, "preview_resolution_nm": target,
                "preview_shape_xy": [w, h], "raw_origin_nm": list(origin),
                "preview_bounds_nm_relative_xyxy": [x0 * target, x1 * target, y0 * target, y1 * target],
                "context_roi": roi is not None}
        return raw, masks, meta

    def tissue_mask(self, raw):
        rule = self.v["tissue"]
        return ((raw >= int(rule["min_intensity"])) &
                (raw <= int(rule["max_intensity"])))

    def outlined(self, frame, text, org, scale=.75, color=(255, 255, 255), thickness=2):
        c = self.cv2
        c.putText(frame, str(text), org, c.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 4, c.LINE_AA)
        c.putText(frame, str(text), org, c.FONT_HERSHEY_SIMPLEX, scale, color, thickness, c.LINE_AA)

    def panel(self, frame, xyxy, alpha=.72):
        a = frame.copy(); self.cv2.rectangle(a, xyxy[:2], xyxy[2:], (0, 0, 0), -1)
        self.cv2.addWeighted(a, alpha, frame, 1 - alpha, 0, frame)

    def fit_full(self, image):
        h, w = image.shape[:2]; s = min(self.W / w, self.H / h)
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        resized = self.cv2.resize(image, (nw, nh), interpolation=self.cv2.INTER_AREA)
        canvas = self.np.zeros((self.H, self.W, 3), self.np.uint8)
        x, y = (self.W - nw) // 2, (self.H - nh) // 2
        canvas[y:y + nh, x:x + nw] = resized
        return canvas, (x, y, nw, nh)

    def draw_scale(self, frame, bar_um, fov_nm=None, display=None, data_width_nm=None):
        nm_per_px = (data_width_nm / display[2]) if display else (fov_nm / self.W)
        length = max(48, min(430, round(bar_um * 1000 / nm_per_px)))
        x2, y = self.W - 70, self.H - 60; x1 = x2 - length
        self.cv2.line(frame, (x1, y), (x2, y), (0, 0, 0), 10, self.cv2.LINE_AA)
        self.cv2.line(frame, (x1, y), (x2, y), (255, 255, 255), 5, self.cv2.LINE_AA)
        label = f"{bar_um:g} um" if bar_um < 1000 else f"{bar_um / 1000:g} mm"
        self.outlined(frame, label, (x1 + length // 2 - 38, y - 16), .70)

    def overlay(self, base, masks, layers, active):
        f = base.copy()
        for layer in layers:
            key = layer["id"]
            if key not in active:
                continue
            m = masks[key]; bgr = self.np.asarray(layer["color_rgb"][::-1], self.np.float32)
            opacity = float(layer.get("opacity", .6))
            f[m] = self.np.clip(f[m].astype(self.np.float32) * (1 - opacity) + bgr * opacity, 0, 255).astype(self.np.uint8)
        return f

    def overview_frame(self, raw, masks, specimen, active, meta):
        raw_canvas, display = self.fit_full(self.cv2.cvtColor(raw, self.cv2.COLOR_GRAY2BGR))
        x, y, w, h = display; canvas_masks = {}
        for k, m in masks.items():
            c = self.np.zeros((self.H, self.W), bool)
            c[y:y + h, x:x + w] = self.cv2.resize(m.astype(self.np.uint8), (w, h), interpolation=self.cv2.INTER_NEAREST) > 0
            canvas_masks[k] = c
        f = self.overlay(raw_canvas, canvas_masks, specimen["layers"], active)
        active_layers = [l for l in specimen["layers"] if l["id"] in active]
        self.panel(f, (42, 42, 720, 120 + 36 * len(active_layers)), .72)
        self.outlined(f, specimen["label"], (72, 88), .98)
        for i, layer in enumerate(active_layers):
            yy = 130 + i * 36
            self.cv2.circle(f, (72, yy - 6), 8, tuple(layer["color_rgb"][::-1]), -1, self.cv2.LINE_AA)
            self.outlined(f, layer["label"], (95, yy), .65)
        self.draw_scale(f, float(self.v["overview_scale_bar_um"]), display=display,
                        data_width_nm=meta["physical_size_nm"][0])
        return f

    def metadata_frame(self, raw, specimen, meta):
        f, display = self.fit_full(self.cv2.cvtColor(raw, self.cv2.COLOR_GRAY2BGR))
        n = meta["size_xy"]; res = meta["resolution_nm"]; p = meta["physical_size_nm"]
        self.panel(f, (48, 700, 900, 1018), .78)
        scope = "bounded context ROI" if meta.get("context_roi") else "whole-section EM"
        self.outlined(f, f"{specimen['label']} | {scope}", (78, 756), 1.03)
        self.outlined(f, f"Native image: {n[0]:,} x {n[1]:,} px", (78, 814), .76)
        self.outlined(f, f"Highest resolution: {res[0]} x {res[1]} nm / pixel", (78, 866), .76)
        self.outlined(f, f"Physical field: {p[0] / 1e6:.3f} x {p[1] / 1e6:.3f} mm", (78, 918), .76)
        self.outlined(f, f"Native pixels: {n[0] * n[1] / 1e9:.3f} gigapixels", (78, 970), .76)
        self.draw_scale(f, float(self.v["overview_scale_bar_um"]), display=display, data_width_nm=p[0])
        return f

    def density(self, mask, tissue, preview_res):
        bin_px = max(1, round(float(self.v["density_bin_um"]) * 1000 / preview_res))
        h, w = mask.shape; ph = math.ceil(h / bin_px) * bin_px; pw = math.ceil(w / bin_px) * bin_px
        mp = self.np.zeros((ph, pw), self.np.uint8); tp = self.np.zeros((ph, pw), self.np.uint8)
        mp[:h, :w] = mask; tp[:h, :w] = tissue
        num = mp.reshape(ph // bin_px, bin_px, pw // bin_px, bin_px).sum((1, 3)).astype(self.np.float32)
        den = tp.reshape(ph // bin_px, bin_px, pw // bin_px, bin_px).sum((1, 3)).astype(self.np.float32)
        num = self.cv2.GaussianBlur(num, (0, 0), 1.25); den = self.cv2.GaussianBlur(den, (0, 0), 1.25)
        dens = self.np.divide(100 * num, den, out=self.np.zeros_like(num), where=den > 0)
        return dens, den > bin_px * bin_px * .06, bin_px

    def density_frame(self, raw, dens, valid, specimen, layer, bin_px, preview_res):
        vals = dens[valid & self.np.isfinite(dens)]; pos = vals[vals > 0]
        q = float(self.v["density_display_quantile"])
        vmax = max(float(self.np.quantile(pos, q)) if pos.size else 1.0, .01)
        norm = self.np.clip(dens / vmax, 0, 1)
        heat = self.cv2.applyColorMap(self.np.uint8(norm * 255), self.cv2.COLORMAP_TURBO)
        heat = self.cv2.resize(heat, (raw.shape[1], raw.shape[0]), interpolation=self.cv2.INTER_LINEAR)
        alpha = self.cv2.resize(valid.astype(self.np.float32), (raw.shape[1], raw.shape[0]), interpolation=self.cv2.INTER_LINEAR)[..., None] * .76
        base = self.cv2.cvtColor(raw, self.cv2.COLOR_GRAY2BGR)
        comp = self.np.clip(base * (1 - alpha) + heat * alpha, 0, 255).astype(self.np.uint8)
        f, _ = self.fit_full(comp)
        self.panel(f, (42, 42, 860, 170), .76)
        self.outlined(f, f"{specimen['label']} | {layer['label']} density", (72, 95), .94)
        self.outlined(f, f"Area fraction within {bin_px * preview_res / 1000:g} um local bins", (72, 142), .68)
        x0, y0, w, h = 1130, 952, 650, 26
        grad = self.np.tile(self.np.arange(256, dtype=self.np.uint8), (h, 1))
        grad = self.cv2.resize(self.cv2.applyColorMap(grad, self.cv2.COLORMAP_TURBO), (w, h))
        f[y0:y0 + h, x0:x0 + w] = grad
        self.outlined(f, "0", (x0, y0 - 14), .58); self.outlined(f, f"{vmax:.2f}%", (x0 + w - 96, y0 - 14), .58)
        self.outlined(f, "Density (%)", (x0 + w // 2 - 70, y0 + 61), .58)
        return f, vmax

    def choose_stops(self, raw, tissue, meta, specimen):
        if specimen.get("stops_um"):
            return [(float(x) * 1000, float(y) * 1000) for x, y in specimen["stops_um"]]
        shrink = max(1, int(math.ceil(max(raw.shape) / 1800)))
        sw, sh = max(1, raw.shape[1] // shrink), max(1, raw.shape[0] // shrink)
        r = self.cv2.resize(raw, (sw, sh), interpolation=self.cv2.INTER_AREA).astype(self.np.float32)
        t = self.cv2.resize(tissue.astype(self.np.float32), (sw, sh), interpolation=self.cv2.INTER_AREA)
        ys, xs = self.np.nonzero(t > .35)
        data_w, data_h = meta["physical_size_nm"]
        context_x0, _, context_y0, _ = meta["preview_bounds_nm_relative_xyxy"]
        if not len(xs):
            raise RuntimeError(f"No valid tissue pixels available for local-stop selection in {specimen['id']}")
        preview = meta["preview_resolution_nm"]; fov_nm = float(self.v["detail_fov_um"]) * 1000
        ww = max(9, round(fov_nm / preview / shrink)); wh = max(7, round(fov_nm * self.H / self.W / preview / shrink))
        coverage = self.cv2.boxFilter(t, -1, (ww, wh), normalize=True, borderType=self.cv2.BORDER_CONSTANT)
        mean = self.cv2.boxFilter(r, -1, (ww, wh), normalize=True, borderType=self.cv2.BORDER_REFLECT)
        mean2 = self.cv2.boxFilter(r * r, -1, (ww, wh), normalize=True, borderType=self.cv2.BORDER_REFLECT)
        score = coverage + .12 * self.np.clip(self.np.sqrt(self.np.maximum(0, mean2 - mean * mean)) / 55, 0, 1)
        mx, my = max(1, ww // 2), max(1, wh // 2)
        score[:my] = score[-my:] = -1; score[:, :mx] = score[:, -mx:] = -1
        selection = specimen.get("story", {}).get("local_stops", {})
        count = int(selection.get("count", 4))
        if selection.get("mode") == "seeded_random":
            threshold = float(selection.get("min_tissue_fraction", 0.70))
            min_distance = float(selection.get("min_center_distance_um", 0.0)) * 1000.0
            eligible_y, eligible_x = self.np.nonzero(coverage >= threshold)
            valid = ((eligible_x >= mx) & (eligible_x < sw - mx) &
                     (eligible_y >= my) & (eligible_y < sh - my))
            eligible_x, eligible_y = eligible_x[valid], eligible_y[valid]
            if not len(eligible_x):
                raise RuntimeError(f"No random local stops meet tissue threshold {threshold}")
            rng = self.np.random.default_rng(int(selection["seed"]))
            order = rng.permutation(len(eligible_x))
            points = []
            for candidate in order:
                point = (context_x0 + (float(eligible_x[candidate]) + .5) * shrink * preview,
                         context_y0 + (float(eligible_y[candidate]) + .5) * shrink * preview)
                if all(math.dist(point, previous) >= min_distance for previous in points):
                    points.append(point)
                    if len(points) == count:
                        return points
            raise RuntimeError(
                f"Could select only {len(points)}/{count} seeded-random stops; "
                "lower min_center_distance_um or tissue threshold"
            )
        points = []
        bands = [(index / count, (index + 1) / count) for index in range(count)]
        for q0, q1 in bands:
            bx0 = max(mx, int(self.np.quantile(xs, q0))); bx1 = min(sw - mx, int(self.np.quantile(xs, q1)) + 1)
            candidate = score[:, bx0:bx1]; iy, ix = self.np.unravel_index(int(self.np.argmax(candidate)), candidate.shape)
            points.append((context_x0 + min(data_w, (bx0 + ix + .5) * shrink * preview),
                           context_y0 + min(data_h, (iy + .5) * shrink * preview)))
        return points

    def load_detail(self, specimen, stops, meta):
        res = int(self.v["detail_resolution_nm"]); fov = float(self.v["detail_fov_um"]) * 1000
        camera = self.v["camera"]
        max_fov_multiplier = max(
            float(camera["entry_start_fov_multiplier"]),
            (1.0 + float(camera["hold_zoom_fraction"])) *
            (1.0 + float(camera["transition_zoom_out_fraction"])),
        )
        fh = fov * self.H / self.W
        margin = max(fov * (0.55 * max_fov_multiplier + float(camera["hold_pan_fraction"])), 180000.0)
        xs = [p[0] for p in stops]; ys = [p[1] for p in stops]
        x0 = max(0, math.floor((min(xs) - fov / 2 - margin) / res)); x1 = math.ceil((max(xs) + fov / 2 + margin) / res)
        y0 = max(0, math.floor((min(ys) - fh / 2 - margin) / res)); y1 = math.ceil((max(ys) + fh / 2 + margin) / res)
        if meta.get("context_roi") and bool(self.v.get("include_overview", True)):
            bx0, bx1, by0, by1 = meta["preview_bounds_nm_relative_xyxy"]
            x0 = min(x0, max(0, math.floor(bx0 / res))); x1 = max(x1, math.ceil(bx1 / res))
            y0 = min(y0, max(0, math.floor(by0 / res))); y1 = max(y1, math.ceil(by1 / res))
        origin = tuple(meta["raw_origin_nm"])
        raw = self.read_aligned(specimen["raw"], res, x0, x1, y0, y1, origin, categorical=False).astype(self.np.uint8)
        masks = {}; cache = {}
        for layer in specimen["layers"]:
            ds = layer["dataset"]
            if ds not in cache:
                cache[ds] = self.read_aligned(ds, res, x0, x1, y0, y1, origin, categorical=True)
            masks[layer["id"]] = self.label_mask(cache[ds], layer.get("label_value"))
        comp = self.overlay(self.cv2.cvtColor(raw, self.cv2.COLOR_GRAY2BGR), masks,
                            specimen["layers"], set(masks))
        return comp, (x0 * res, y0 * res)

    def crop_detail(self, image, cx_nm, cy_nm, fov_nm, origin_nm):
        res = int(self.v["detail_resolution_nm"]); fh = fov_nm * self.H / self.W
        x0 = math.floor((cx_nm - fov_nm / 2 - origin_nm[0]) / res); x1 = math.ceil((cx_nm + fov_nm / 2 - origin_nm[0]) / res)
        y0 = math.floor((cy_nm - fh / 2 - origin_nm[1]) / res); y1 = math.ceil((cy_nm + fh / 2 - origin_nm[1]) / res)
        h, w = image.shape[:2]; ax0, ax1 = max(0, x0), min(w, x1); ay0, ay1 = max(0, y0), min(h, y1)
        crop = self.np.zeros((max(1, y1 - y0), max(1, x1 - x0), 3), self.np.uint8)
        if ax1 > ax0 and ay1 > ay0:
            crop[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0] = image[ay0:ay1, ax0:ax1]
        return self.cv2.resize(crop, (self.W, self.H), interpolation=self.cv2.INTER_LINEAR)

    def stop_info(self, frame, index, center, fov_nm=None):
        fov = float(fov_nm if fov_nm is not None else float(self.v["detail_fov_um"]) * 1000)
        fh = fov * self.H / self.W; cx, cy = center
        self.panel(frame, (42, 830, 970, 1030), .76)
        self.outlined(frame, f"Representative field {index + 1}", (72, 878), .90)
        self.outlined(frame, f"X: {(cx - fov / 2) / 1000:.1f}-{(cx + fov / 2) / 1000:.1f} um", (72, 932), .68)
        self.outlined(frame, f"Y: {(cy - fh / 2) / 1000:.1f}-{(cy + fh / 2) / 1000:.1f} um", (72, 976), .68)
        self.outlined(frame, f"Field of view: {fov / 1000:.1f} x {fh / 1000:.1f} um", (72, 1016), .68)

    def output_dir(self, specimen):
        return self.output_root / specimen["id"]

    def build_assets(self, specimen):
        out = self.output_dir(specimen); assets = out / "assets"; assets.mkdir(parents=True, exist_ok=True)
        raw, masks, meta = self.read_preview(specimen); tissue = self.tissue_mask(raw)
        frames = {"metadata": self.metadata_frame(raw, specimen, meta)}; density_meta = {}
        for layer in specimen["layers"]:
            k = layer["id"]
            frames[f"overlay_{k}"] = self.overview_frame(raw, masks, specimen, {k}, meta)
            dens, valid, bin_px = self.density(masks[k], tissue, meta["preview_resolution_nm"])
            frames[f"density_{k}"], vmax = self.density_frame(raw, dens, valid, specimen, layer, bin_px, meta["preview_resolution_nm"])
            density_meta[k] = {"display_vmax_percent": vmax, "bin_px": bin_px,
                               "bin_um": bin_px * meta["preview_resolution_nm"] / 1000}
        frames["all"] = self.overview_frame(raw, masks, specimen, set(masks), meta)
        for name, frame in frames.items():
            self.cv2.imwrite(str(assets / f"{name}.png"), frame, [self.cv2.IMWRITE_PNG_COMPRESSION, 3])
        stops = self.choose_stops(raw, tissue, meta, specimen)
        detail, detail_origin = self.load_detail(specimen, stops, meta)
        manifest = {
            "project_name": self.cfg["project_name"], "specimen": specimen,
            "preview_meta": meta, "density": density_meta,
            "stops_nm_relative_to_raw_origin": stops, "detail_origin_nm_relative": detail_origin,
            "camera_motion": self.v["camera"], "config": str(self.config_path),
        }
        (out / "asset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(self.config_path, out / "project_config.json")
        self.write_ngvideo(specimen, manifest)
        return frames, stops, detail, detail_origin, manifest

    def load_approved_assets(self, specimen):
        out = self.output_dir(specimen); assets = out / "assets"
        manifest = json.loads((out / "asset_manifest.json").read_text(encoding="utf-8"))
        names = ["metadata", "all"]
        for layer in specimen["layers"]:
            names += [f"overlay_{layer['id']}", f"density_{layer['id']}"]
        frames = {n: self.cv2.imread(str(assets / f"{n}.png"), self.cv2.IMREAD_COLOR) for n in names}
        missing = [n for n, f in frames.items() if f is None]
        if missing:
            raise RuntimeError(f"Missing approved assets: {missing}")
        stops = [tuple(x) for x in manifest["stops_nm_relative_to_raw_origin"]]
        detail, detail_origin = self.load_detail(specimen, stops, manifest["preview_meta"])
        return frames, stops, detail, detail_origin, manifest

    def storyboard(self, specimen):
        frames, stops, detail, origin, manifest = self.build_assets(specimen)
        thumbs = []
        if bool(self.v.get("include_overview", True)):
            thumbs.append(frames["metadata"])
            for layer in specimen["layers"]:
                thumbs += [frames[f"overlay_{layer['id']}"] , frames[f"density_{layer['id']}"]]
            thumbs.append(frames["all"])
        fov = float(self.v["detail_fov_um"]) * 1000
        for i, p in enumerate(stops):
            f = self.crop_detail(detail, *p, fov, origin)
            self.draw_scale(f, float(self.v["detail_scale_bar_um"]), fov_nm=fov); self.stop_info(f, i, p)
            thumbs.append(f)
        tw, th, cols = 480, 270, 4; rows = math.ceil(len(thumbs) / cols)
        sheet = self.np.zeros((rows * th, cols * tw, 3), self.np.uint8)
        for i, f in enumerate(thumbs):
            sheet[(i // cols) * th:(i // cols + 1) * th, (i % cols) * tw:(i % cols + 1) * tw] = self.cv2.resize(f, (tw, th), interpolation=self.cv2.INTER_AREA)
        out = self.output_dir(specimen); self.cv2.imwrite(str(out / "storyboard.jpg"), sheet, [self.cv2.IMWRITE_JPEG_QUALITY, 93])
        print(f"DONE_STORYBOARD {specimen['id']} {out / 'storyboard.jpg'}", flush=True)

    def camera_frame(self, t, all_frame, stops, detail, origin, context_center=None):
        base_fov = float(self.v["detail_fov_um"]) * 1000
        include_overview = bool(self.v.get("include_overview", True))
        pose = camera_pose(
            t, stops, base_fov, self.v["zoom_seconds"], self.v["hold_seconds"],
            self.v["move_seconds"], include_overview, self.v["camera"], context_center,
        )
        center, fov = pose["center"], pose["fov_nm"]
        target = self.crop_detail(detail, *center, fov, origin)
        if pose["phase"] == "entry_zoom" and include_overview:
            f = self.cv2.addWeighted(all_frame, 1.0 - pose["progress"], target, pose["progress"], 0)
        else:
            f = target
        self.draw_scale(f, float(self.v["detail_scale_bar_um"]), fov_nm=fov)
        if pose["stop_index"] is not None:
            self.stop_info(f, pose["stop_index"], center, fov)
        return f

    def render(self, specimen, reuse_assets=False, force=False):
        out = self.output_dir(specimen); out.mkdir(parents=True, exist_ok=True)
        approved = (out / "storyboard.jpg").is_file() and (out / "asset_manifest.json").is_file()
        if reuse_assets:
            if not approved:
                raise RuntimeError(f"No approved storyboard assets for {specimen['id']}")
            frames, stops, detail, origin, manifest = self.load_approved_assets(specimen)
        else:
            frames, stops, detail, origin, manifest = self.build_assets(specimen)
            self.storyboard_from_loaded(specimen, frames, stops, detail, origin)
        frame_dir = out / "frames"
        if frame_dir.exists() and any(frame_dir.glob("*.png")):
            if not force:
                raise RuntimeError(f"Stale PNG frames exist in {frame_dir}; rerun with --force")
            shutil.rmtree(frame_dir)
        frame_dir.mkdir(exist_ok=True)
        video = out / f"{specimen['id']}_cloudvolume_tour.mp4"
        writer = self.cv2.VideoWriter(str(video), self.cv2.VideoWriter_fourcc(*str(self.v["codec"])), self.FPS, (self.W, self.H))
        if not writer.isOpened():
            raise RuntimeError(f"Video writer failed for codec {self.v['codec']}")
        timeline = []; index = 0; previous = None; write_png = bool(self.v["png_frames"])

        def emit(frame):
            nonlocal index, previous
            if write_png:
                self.cv2.imwrite(str(frame_dir / f"{index:07d}.png"), frame,
                                 [self.cv2.IMWRITE_PNG_COMPRESSION, int(self.v["png_compression"])])
            writer.write(frame); previous = frame; index += 1

        def static(label, target, seconds, kind):
            nonlocal previous
            start = index / self.FPS; count = round(float(seconds) * self.FPS); source = previous
            for j in range(count):
                if source is not None and j < int(self.v["fade_frames"]):
                    a = smoothstep(j / max(1, int(self.v["fade_frames"]) - 1)); f = self.cv2.addWeighted(source, 1 - a, target, a, 0)
                else:
                    f = target
                emit(f)
            timeline.append({"label": label, "kind": kind, "start_seconds": start, "end_seconds": index / self.FPS})

        include_overview = bool(self.v.get("include_overview", True))
        if include_overview:
            scope_label = "Bounded context" if manifest["preview_meta"].get("context_roi") else "Whole-section metadata"
            static(scope_label, frames["metadata"], self.v["metadata_seconds"], "metadata")
            for layer in specimen["layers"]:
                k = layer["id"]
                static(layer["label"], frames[f"overlay_{k}"], self.v["isolated_seconds"], "isolated_overlay")
                static(layer["label"] + " density", frames[f"density_{k}"], self.v["density_seconds"], "density")
            static("All structures", frames["all"], self.v["all_seconds"], "all_layers")
        camera_seconds = ((float(self.v["zoom_seconds"]) if include_overview else 0.0) + len(stops) * float(self.v["hold_seconds"]) +
                          (len(stops) - 1) * float(self.v["move_seconds"]))
        bx0, bx1, by0, by1 = manifest["preview_meta"]["preview_bounds_nm_relative_xyxy"]
        context_center = ((bx0 + bx1) / 2, (by0 + by1) / 2)
        start = index / self.FPS; source = previous; count = round(camera_seconds * self.FPS)
        for j in range(count):
            target = self.camera_frame(j / self.FPS, frames["all"], stops, detail, origin, context_center)
            if source is not None and j < int(self.v["fade_frames"]):
                a = smoothstep(j / max(1, int(self.v["fade_frames"]) - 1)); target = self.cv2.addWeighted(source, 1 - a, target, a, 0)
            emit(target)
            if j % (self.FPS * 5) == 0:
                print(f"RENDER {specimen['id']} camera={j}/{count} total_frames={index}", flush=True)
        timeline.append({"label": "Representative-field camera tour", "kind": "camera_tour",
                         "start_seconds": start, "end_seconds": index / self.FPS})
        writer.release()
        manifest.update({"video": str(video), "width": self.W, "height": self.H, "fps": self.FPS,
                         "frame_count": index, "duration_seconds": index / self.FPS,
                         "timeline": timeline, "frames": str(frame_dir) if write_png else None})
        (out / "keyframes.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(Path(__file__), out / "cloudvolume_video.py")
        print(f"DONE_VIDEO {specimen['id']} frames={index} seconds={index / self.FPS}", flush=True)

    def storyboard_from_loaded(self, specimen, frames, stops, detail, origin):
        # Used when render is intentionally run without a prior approval stage.
        thumbs = []
        if bool(self.v.get("include_overview", True)):
            thumbs.append(frames["metadata"])
            for layer in specimen["layers"]:
                thumbs += [frames[f"overlay_{layer['id']}"] , frames[f"density_{layer['id']}"]]
            thumbs.append(frames["all"])
        fov = float(self.v["detail_fov_um"]) * 1000
        for i, p in enumerate(stops):
            f = self.crop_detail(detail, *p, fov, origin); self.draw_scale(f, float(self.v["detail_scale_bar_um"]), fov_nm=fov); self.stop_info(f, i, p); thumbs.append(f)
        tw, th, cols = 480, 270, 4; sheet = self.np.zeros((math.ceil(len(thumbs) / cols) * th, cols * tw, 3), self.np.uint8)
        for i, f in enumerate(thumbs): sheet[(i // cols) * th:(i // cols + 1) * th, (i % cols) * tw:(i % cols + 1) * tw] = self.cv2.resize(f, (tw, th), interpolation=self.cv2.INTER_AREA)
        self.cv2.imwrite(str(self.output_dir(specimen) / "storyboard.jpg"), sheet, [self.cv2.IMWRITE_JPEG_QUALITY, 93])

    def write_ngvideo(self, specimen, manifest):
        out = self.output_dir(specimen); ng = self.cfg.get("neuroglancer", {})
        base = ng.get("base_url", "http://127.0.0.1:1337"); viewer = ng.get("viewer_url", "https://neuroglancer-demo.appspot.com/")
        meta = manifest["preview_meta"]; native_res = meta["resolution_nm"][0]
        raw_origin = meta["raw_origin_nm"]
        bx0, bx1, by0, by1 = meta["preview_bounds_nm_relative_xyxy"]
        center_world = (raw_origin[0] + (bx0 + bx1) / 2,
                        raw_origin[1] + (by0 + by1) / 2)
        overview_scale = max(meta["size_xy"][0] / self.W, meta["size_xy"][1] / self.H) * 1.08
        def state(active, center=center_world, scale=overview_scale):
            layers = [{"type": "image", "source": f"precomputed://{base}/{specimen['raw']}", "name": "Original"}]
            for layer in specimen["layers"]:
                segs = [str(x) for x in layer.get("segment_ids", ([1] if layer.get("label_value") is None else
                        (layer["label_value"] if isinstance(layer["label_value"], list) else [layer["label_value"]])))]
                color = "#%02x%02x%02x" % tuple(layer["color_rgb"])
                layers.append({"type": "segmentation", "source": f"precomputed://{base}/{layer['dataset']}",
                               "name": layer["label"], "segments": segs,
                               "segmentColors": {s: color for s in segs},
                               "selectedAlpha": float(layer.get("opacity", .6)) if layer["id"] in active else 0,
                               "notSelectedAlpha": 0,
                               "objectAlpha": float(layer.get("object_alpha", 0)) if layer["id"] in active else 0})
            return {"position": [center[0] / native_res, center[1] / native_res, .5],
                    "crossSectionScale": scale, "crossSectionOrientation": [0, 0, 0, 1],
                    "layers": layers, "layout": ng.get("layout", "xy"),
                    "showAxisLines": bool(ng.get("show_axis_lines", False)),
                    "showScaleBar": bool(ng.get("show_scale_bar", True)),
                    "crossSectionBackgroundColor": ng.get("background", "#000000"),
                    "selectedLayer": {"visible": False}}
        include_overview = bool(self.v.get("include_overview", True))
        t = 0.0; states = []
        if include_overview:
            states.append((t, state(set()))); t += float(self.v["metadata_seconds"])
            for layer in specimen["layers"]:
                states.append((t, state({layer["id"]}))); t += float(self.v["isolated_seconds"]) + float(self.v["density_seconds"])
        active = {x["id"] for x in specimen["layers"]}
        if include_overview:
            states.append((t, state(active))); t += float(self.v["all_seconds"]) + float(self.v["zoom_seconds"])
        detail_scale = float(self.v["detail_fov_um"]) * 1000 / self.W / native_res
        for i, p in enumerate(manifest["stops_nm_relative_to_raw_origin"]):
            center = (raw_origin[0] + p[0], raw_origin[1] + p[1]); states.append((t, state(active, center, detail_scale)))
            t += float(self.v["hold_seconds"])
            if i < len(manifest["stops_nm_relative_to_raw_origin"]) - 1: t += float(self.v["move_seconds"])
        lines = []
        for i, (at, s) in enumerate(states):
            url = viewer.rstrip("/") + "/#!" + quote(json.dumps(s, separators=(",", ":")), safe="")
            duration = states[i + 1][0] - at if i + 1 < len(states) else 0
            lines += [url, str(duration)]
        (out / "tour.ngvideo").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def audit_specimen(self, specimen):
        datasets = [("raw", specimen["raw"])] + [(x["id"], x["dataset"]) for x in specimen["layers"]]
        unique = {}; records = []
        for role, dataset in datasets:
            if dataset in unique:
                continue
            unique[dataset] = True; cv = self.volume(dataset); native = self.native_meta(dataset)
            sample_mip = max(cv.available_mips); cv.mip = sample_mip; b = cv.bounds
            sx = min(1024, int(b.maxpt[0] - b.minpt[0])); sy = min(1024, int(b.maxpt[1] - b.minpt[1]))
            centers = [(int((b.minpt[0] + b.maxpt[0]) / 2), int((b.minpt[1] + b.maxpt[1]) / 2))]
            counts = {}
            if role != "raw":
                for cx, cy in centers:
                    x0 = max(int(b.minpt[0]), cx - sx // 2); y0 = max(int(b.minpt[1]), cy - sy // 2)
                    a = self._read_query(cv, x0, min(int(b.maxpt[0]), x0 + sx), y0, min(int(b.maxpt[1]), y0 + sy))
                    vals, nums = self.np.unique(a, return_counts=True)
                    for val, num in zip(vals.tolist(), nums.tolist()): counts[str(val)] = counts.get(str(val), 0) + num
            records.append({"dataset": dataset, "roles": [r for r, d in datasets if d == dataset],
                            "native": native, "sample_mip": int(sample_mip), "sample_label_counts": counts})
        raw_meta = records[0]["native"]; issues = []
        for r in records[1:]:
            if r["native"]["physical_size_nm"] != raw_meta["physical_size_nm"] or r["native"]["origin_nm"] != raw_meta["origin_nm"]:
                issues.append({"dataset": r["dataset"], "issue": "physical extent/origin differs from raw"})
        n_layers = len(specimen["layers"]); include_overview = bool(self.v.get("include_overview", True))
        overview_duration = (float(self.v["metadata_seconds"]) + n_layers *
            (float(self.v["isolated_seconds"]) + float(self.v["density_seconds"])) + float(self.v["all_seconds"]) +
            float(self.v["zoom_seconds"])) if include_overview else 0.0
        stop_count = (len(specimen.get("stops_um") or []) or
                      int(specimen.get("story", {}).get("local_stops", {}).get("count", 4)))
        duration = (overview_duration + stop_count * float(self.v["hold_seconds"]) +
                    max(0, stop_count - 1) * float(self.v["move_seconds"]))
        return {"specimen": specimen["id"], "datasets": records, "issues": issues,
                "expected_duration_seconds": duration, "expected_frames": round(duration * self.FPS)}

    def audit(self, specimens):
        self.output_root.mkdir(parents=True, exist_ok=True)
        report = {"project": self.cfg["project_name"], "config": str(self.config_path),
                  "specimens": [self.audit_specimen(x) for x in specimens]}
        try:
            usage = shutil.disk_usage(self.output_root)
            report["output_disk"] = {"total": usage.total, "used": usage.used, "free": usage.free}
        except OSError:
            pass
        (self.output_root / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        if any(x["issues"] for x in report["specimens"]):
            print("AUDIT_WARNING physical alignment issues require review", file=sys.stderr)

    def verify(self, specimen):
        out = self.output_dir(specimen); video = out / f"{specimen['id']}_cloudvolume_tour.mp4"
        cap = self.cv2.VideoCapture(str(video))
        r = {"opened": bool(cap.isOpened()), "width": int(cap.get(self.cv2.CAP_PROP_FRAME_WIDTH)),
             "height": int(cap.get(self.cv2.CAP_PROP_FRAME_HEIGHT)), "fps": float(cap.get(self.cv2.CAP_PROP_FPS)),
             "frame_count": int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))}
        r["duration_seconds"] = r["frame_count"] / r["fps"] if r["fps"] else None
        samples = self.np.linspace(0, max(0, r["frame_count"] - 1), 12).astype(int).tolist()
        thumbs = []; decoded = {}
        for n in samples:
            cap.set(self.cv2.CAP_PROP_POS_FRAMES, n); ok, f = cap.read(); decoded[str(n)] = bool(ok)
            thumbs.append(self.cv2.resize(f, (480, 270), interpolation=self.cv2.INTER_AREA) if ok else self.np.zeros((270, 480, 3), self.np.uint8))
        cap.release(); sheet = self.np.zeros((810, 1920, 3), self.np.uint8)
        for i, f in enumerate(thumbs): sheet[(i // 4) * 270:(i // 4 + 1) * 270, (i % 4) * 480:(i % 4 + 1) * 480] = f
        self.cv2.imwrite(str(out / "verification_contact_sheet.jpg"), sheet, [self.cv2.IMWRITE_JPEG_QUALITY, 93])
        pngs = sorted((out / "frames").glob("*.png")) if bool(self.v["png_frames"]) else []
        r.update({"decoded_samples": decoded, "png_count": len(pngs) if bool(self.v["png_frames"]) else None})
        h = hashlib.sha256()
        with video.open("rb") as fh:
            for block in iter(lambda: fh.read(8 * 1024 * 1024), b""): h.update(block)
        r["sha256"] = h.hexdigest()
        expected_ok = (r["opened"] and r["width"] == self.W and r["height"] == self.H and
                       abs(r["fps"] - self.FPS) < .05 and all(decoded.values()) and
                       (not bool(self.v["png_frames"]) or len(pngs) == r["frame_count"]))
        r["passed"] = bool(expected_ok)
        (out / "verification.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
        (out / "SHA256SUMS.txt").write_text(f"{r['sha256']}  {video.name}\n", encoding="utf-8")
        print(json.dumps(r, indent=2), flush=True)
        if not r["passed"]:
            raise RuntimeError(f"Verification failed for {specimen['id']}")

    def finalize(self, specimens):
        self.output_root.mkdir(parents=True, exist_ok=True)
        records = []; sha = []; storyboards = []; verification_sheets = []
        for specimen in specimens:
            out = self.output_dir(specimen)
            vr = json.loads((out / "verification.json").read_text(encoding="utf-8"))
            kf = json.loads((out / "keyframes.json").read_text(encoding="utf-8"))
            video = Path(kf["video"])
            records.append({"id": specimen["id"], "label": specimen["label"], "layers": specimen["layers"],
                            "video": str(video), "frame_count": vr["frame_count"], "png_count": vr["png_count"],
                            "duration_seconds": vr["duration_seconds"], "video_bytes": video.stat().st_size,
                            "sha256": vr["sha256"], "passed": vr["passed"]})
            sha.append(f"{vr['sha256']}  {video.relative_to(self.output_root)}")
            storyboards.append(self.cv2.imread(str(out / "storyboard.jpg")))
            verification_sheets.append(self.cv2.imread(str(out / "verification_contact_sheet.jpg")))
        delivery = {"project": self.cfg["project_name"], "config": str(self.config_path),
                    "video_standard": {k: self.v[k] for k in ("width", "height", "fps", "codec")},
                    "specimens": records}
        (self.output_root / "delivery_manifest.json").write_text(json.dumps(delivery, indent=2) + "\n", encoding="utf-8")
        (self.output_root / "SHA256SUMS.txt").write_text("\n".join(sha) + "\n", encoding="utf-8")
        shutil.copy2(self.config_path, self.output_root / "project_config.json")
        shutil.copy2(Path(__file__), self.output_root / "cloudvolume_video.py")
        self._montage(storyboards, self.output_root / "all_storyboards.jpg")
        self._montage(verification_sheets, self.output_root / "all_verification_contact_sheets.jpg")
        print(json.dumps({"output_root": str(self.output_root), "specimens": len(records),
                          "total_frames": sum(x["frame_count"] for x in records),
                          "total_video_bytes": sum(x["video_bytes"] for x in records)}, indent=2), flush=True)

    def _montage(self, images, path):
        cols = min(3, max(1, len(images))); rows = math.ceil(len(images) / cols); tw, th = 640, 360
        sheet = self.np.zeros((rows * th, cols * tw, 3), self.np.uint8)
        for i, im in enumerate(images):
            if im is not None:
                sheet[(i // cols) * th:(i // cols + 1) * th, (i % cols) * tw:(i % cols + 1) * tw] = self.cv2.resize(im, (tw, th), interpolation=self.cv2.INTER_AREA)
        self.cv2.imwrite(str(path), sheet, [self.cv2.IMWRITE_JPEG_QUALITY, 94])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["audit", "storyboard", "render", "verify", "finalize"])
    p.add_argument("config", type=Path)
    p.add_argument("--specimen", action="append", default=[])
    p.add_argument("--reuse-assets", action="store_true")
    p.add_argument("--force", action="store_true", help="replace stale PNG frames in selected output directories")
    a = p.parse_args(); pipeline = Pipeline(a.config); specimens = pipeline.specimens(a.specimen)
    if a.command == "audit": pipeline.audit(specimens)
    elif a.command == "storyboard":
        for specimen in specimens: pipeline.storyboard(specimen)
    elif a.command == "render":
        for specimen in specimens: pipeline.render(specimen, a.reuse_assets, a.force)
    elif a.command == "verify":
        for specimen in specimens: pipeline.verify(specimen)
    elif a.command == "finalize": pipeline.finalize(specimens)


if __name__ == "__main__":
    main()
