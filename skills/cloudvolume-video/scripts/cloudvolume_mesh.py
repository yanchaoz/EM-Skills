#!/usr/bin/env python3
"""Audit, export, render, and verify bounded CloudVolume-compatible meshes.

The renderer is intentionally headless: it rasterizes shaded triangles with
NumPy and OpenCV instead of requiring an OpenGL context. Heavy readers are
imported only for the source type that needs them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MeshData:
    vertices: Any
    faces: Any
    provenance: dict[str, Any]


def _np():
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("NumPy is required for mesh operations") from exc
    return np


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("OpenCV is required for mesh rendering and verification") from exc
    return cv2


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg.get("output_root"), str) or not cfg["output_root"]:
        raise ValueError("output_root must be a non-empty string")
    scenes = cfg.get("mesh_scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("mesh_scenes must contain at least one scene")
    seen = set()
    for scene in scenes:
        sid = scene.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("every mesh scene needs a unique non-empty id")
        seen.add(sid)
        if scene.get("source", {}).get("type") not in {"precomputed", "labels", "file"}:
            raise ValueError(f"{sid}: source.type must be precomputed, labels, or file")
    return cfg


def selected_scenes(cfg: dict[str, Any], scene_ids: list[str] | None) -> list[dict[str, Any]]:
    scenes = cfg["mesh_scenes"]
    if not scene_ids:
        return scenes
    by_id = {x["id"]: x for x in scenes}
    missing = [x for x in scene_ids if x not in by_id]
    if missing:
        raise ValueError(f"unknown scene id(s): {', '.join(missing)}")
    return [by_id[x] for x in scene_ids]


def _as_mesh(vertices: Any, faces: Any, provenance: dict[str, Any]) -> MeshData:
    np = _np()
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ValueError("mesh vertices must have shape (N, 3) and be non-empty")
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces):
        raise ValueError("mesh faces must have shape (M, 3) and be non-empty")
    if not np.isfinite(vertices).all():
        raise ValueError("mesh contains non-finite vertices")
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("mesh face indices are out of bounds")
    return MeshData(vertices, faces, provenance)


def _merge_meshes(meshes: list[MeshData], provenance: dict[str, Any]) -> MeshData:
    np = _np()
    if not meshes:
        raise ValueError("no non-empty meshes were returned")
    vertices, faces, offset = [], [], 0
    for mesh in meshes:
        vertices.append(mesh.vertices)
        faces.append(mesh.faces + offset)
        offset += len(mesh.vertices)
    return _as_mesh(np.concatenate(vertices), np.concatenate(faces), provenance)


def _load_file(source: dict[str, Any], base: Path) -> MeshData:
    np = _np()
    path = Path(source["path"])
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".npz":
        data = np.load(path, allow_pickle=False)
        return _as_mesh(data["vertices"], data["faces"], {"type": "file", "path": str(path)})
    try:
        import trimesh
    except ImportError as exc:
        raise SystemExit("trimesh is required to read mesh files other than .npz") from exc
    loaded = trimesh.load(path, force="mesh", process=False)
    if hasattr(loaded, "geometry"):
        loaded = trimesh.util.concatenate(tuple(loaded.geometry.values()))
    return _as_mesh(loaded.vertices, loaded.faces, {"type": "file", "path": str(path)})


def _load_labels(source: dict[str, Any], base: Path) -> MeshData:
    np = _np()
    path = Path(source["path"])
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".npy":
        labels = np.load(path, mmap_mode="r")
    elif suffix == ".npz":
        key = source.get("array_key", "labels")
        labels = np.load(path, allow_pickle=False)[key]
    elif suffix in {".tif", ".tiff"}:
        try:
            import tifffile
        except ImportError as exc:
            raise SystemExit("tifffile is required for TIFF label volumes") from exc
        labels = tifffile.imread(path)
    else:
        raise ValueError("label sources must be .npy, .npz, .tif, or .tiff")
    if source.get("axes", "zyx").lower() != "zyx" or labels.ndim != 3:
        raise ValueError("label mesh extraction currently requires a 3D zyx array")
    roi = source.get("roi_zyx")
    if not (isinstance(roi, list) and len(roi) == 6):
        raise ValueError("labels source requires bounded roi_zyx=[z0,z1,y0,y1,x0,x1]")
    z0, z1, y0, y1, x0, x1 = map(int, roi)
    if min(z0, y0, x0) < 0 or z1 > labels.shape[0] or y1 > labels.shape[1] or x1 > labels.shape[2]:
        raise ValueError("roi_zyx lies outside the label volume")
    if z1 <= z0 or y1 <= y0 or x1 <= x0:
        raise ValueError("roi_zyx must have positive extent")
    crop = np.asarray(labels[z0:z1, y0:y1, x0:x1])
    ids = [int(x) for x in source.get("segment_ids", [])]
    if not ids:
        raise ValueError("labels source requires one or more non-zero segment_ids")
    if any(x == 0 for x in ids):
        raise ValueError("segment_ids must not include background label 0")
    mask = np.isin(crop, ids)
    if not mask.any():
        raise ValueError("requested segment_ids are absent from roi_zyx")
    try:
        from skimage.measure import marching_cubes
    except ImportError as exc:
        raise SystemExit("scikit-image is required for marching cubes") from exc
    resolution_zyx = np.asarray(source.get("resolution_nm_zyx"), dtype=np.float64)
    if resolution_zyx.shape != (3,) or (resolution_zyx <= 0).any():
        raise ValueError("labels source requires positive resolution_nm_zyx=[z,y,x]")
    padded = np.pad(mask.astype(np.uint8), 1)
    verts_zyx, faces, _, _ = marching_cubes(padded, 0.5, spacing=tuple(resolution_zyx))
    verts_zyx -= resolution_zyx
    voxel_offset_zyx = np.asarray(source.get("voxel_offset_zyx", [0, 0, 0]), dtype=np.float64)
    origin_zyx_nm = (voxel_offset_zyx + np.asarray([z0, y0, x0])) * resolution_zyx
    verts_zyx += origin_zyx_nm
    vertices_xyz = verts_zyx[:, ::-1]
    return _as_mesh(vertices_xyz, faces, {
        "type": "labels", "path": str(path), "segment_ids": ids,
        "roi_zyx": [z0, z1, y0, y1, x0, x1],
        "resolution_nm_zyx": resolution_zyx.tolist(),
        "voxel_offset_zyx": voxel_offset_zyx.tolist(),
        "coordinates": "nm",
    })


def _load_precomputed(source: dict[str, Any]) -> MeshData:
    np = _np()
    try:
        from cloudvolume import CloudVolume
    except ImportError as exc:
        raise SystemExit("cloud-volume is required for precomputed mesh sources") from exc
    uri = source.get("uri")
    if not uri:
        raise ValueError("precomputed source requires uri")
    ids = [int(x) for x in source.get("segment_ids", [])]
    if not ids:
        raise ValueError("precomputed source requires segment_ids")
    cv = CloudVolume(uri, mip=int(source.get("mip", 0)), progress=False, fill_missing=False)
    result = cv.mesh.get(ids, fuse=True)
    values = list(result.values()) if isinstance(result, dict) else [result]
    meshes = []
    for item in values:
        if item is None or not len(item.vertices) or not len(item.faces):
            continue
        vertices = np.asarray(item.vertices, dtype=np.float64)
        coordinates = source.get("coordinates", "nm")
        if coordinates == "voxel":
            resolution = np.asarray(source.get("resolution_nm_xyz", cv.resolution), dtype=np.float64)
            offset = np.asarray(source.get("voxel_offset_xyz", cv.voxel_offset), dtype=np.float64)
            vertices = (vertices + offset) * resolution
        elif coordinates != "nm":
            raise ValueError("precomputed coordinates must be nm or voxel")
        meshes.append(_as_mesh(vertices, item.faces, {}))
    return _merge_meshes(meshes, {
        "type": "precomputed", "uri": uri, "segment_ids": ids,
        "mip": int(source.get("mip", 0)), "coordinates": source.get("coordinates", "nm"),
    })


def load_mesh(scene: dict[str, Any], config_path: Path) -> MeshData:
    source = scene["source"]
    if source["type"] == "file":
        return _load_file(source, config_path.parent)
    if source["type"] == "labels":
        return _load_labels(source, config_path.parent)
    return _load_precomputed(source)


def mesh_metrics(mesh: MeshData) -> dict[str, Any]:
    np = _np()
    bounds = np.vstack((mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)))
    tri = mesh.vertices[mesh.faces]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()
    used = np.unique(mesh.faces)
    return {
        "vertex_count": int(len(mesh.vertices)), "face_count": int(len(mesh.faces)),
        "used_vertex_count": int(len(used)), "orphan_vertex_count": int(len(mesh.vertices) - len(used)),
        "bounds_xyz_nm": bounds.tolist(), "extent_xyz_nm": (bounds[1] - bounds[0]).tolist(),
        "surface_area_nm2": float(area), "finite": bool(np.isfinite(mesh.vertices).all()),
        "face_indices_valid": bool(mesh.faces.min() >= 0 and mesh.faces.max() < len(mesh.vertices)),
    }


def write_ply(path: Path, mesh: MeshData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(mesh.vertices)}\n")
        handle.write("property float x\nproperty float y\nproperty float z\n")
        handle.write(f"element face {len(mesh.faces)}\n")
        handle.write("property list uchar int vertex_indices\nend_header\n")
        for x, y, z in mesh.vertices:
            handle.write(f"{x:.7g} {y:.7g} {z:.7g}\n")
        for a, b, c in mesh.faces:
            handle.write(f"3 {int(a)} {int(b)} {int(c)}\n")


def _rotation(azimuth_deg: float, elevation_deg: float):
    np = _np()
    az, el = np.deg2rad([azimuth_deg, elevation_deg])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(el), -math.sin(el)], [0, math.sin(el), math.cos(el)]])
    return rx @ rz


def render_frame(mesh: MeshData, render: dict[str, Any], azimuth_deg: float):
    np, cv2 = _np(), _cv2()
    width, height = int(render.get("width", 1280)), int(render.get("height", 720))
    if width < 320 or height < 240:
        raise ValueError("render dimensions must be at least 320 x 240")
    bg = tuple(int(x) for x in render.get("background_rgb", [9, 14, 23]))[::-1]
    image = np.full((height, width, 3), bg, dtype=np.uint8)
    vertices = mesh.vertices - mesh.vertices.mean(axis=0)
    rotation = _rotation(azimuth_deg, float(render.get("elevation_deg", 22.0)))
    camera = vertices @ rotation.T
    span = max(float(np.ptp(camera[:, 0])), float(np.ptp(camera[:, 1])), 1e-9)
    scale = float(render.get("fill_fraction", 0.76)) * min(width, height) / span
    xy = camera[:, :2] * scale
    projected = np.column_stack((xy[:, 0] + width / 2, height / 2 - xy[:, 1]))
    faces = mesh.faces
    max_faces = int(render.get("max_render_faces", 120000))
    display_sampled = max_faces > 0 and len(faces) > max_faces
    if display_sampled:
        if not bool(render.get("allow_face_sampling", False)):
            raise ValueError(
                f"mesh has {len(faces)} faces, above max_render_faces={max_faces}; "
                "provide a display LOD/decimated mesh or explicitly set allow_face_sampling=true"
            )
        indices = np.linspace(0, len(faces) - 1, max_faces, dtype=np.int64)
        faces = faces[indices]
    tri3 = camera[faces]
    normals = np.cross(tri3[:, 1] - tri3[:, 0], tri3[:, 2] - tri3[:, 0])
    norm = np.linalg.norm(normals, axis=1)
    valid = norm > 1e-12
    normals[valid] /= norm[valid, None]
    # Backface culling is optional because winding conventions vary by source.
    if bool(render.get("backface_culling", False)):
        valid &= normals[:, 2] > 0
    light = np.asarray(render.get("light_xyz", [-0.3, -0.45, 0.84]), dtype=float)
    light /= np.linalg.norm(light)
    shade = np.clip(0.30 + 0.70 * np.abs(normals @ light), 0, 1)
    smooth_shading = bool(render.get("smooth_shading", True))
    vertex_shade = None
    if smooth_shading:
        vertex_normals = np.zeros_like(camera)
        np.add.at(vertex_normals, faces[:, 0], normals)
        np.add.at(vertex_normals, faces[:, 1], normals)
        np.add.at(vertex_normals, faces[:, 2], normals)
        vertex_norm = np.linalg.norm(vertex_normals, axis=1)
        nonzero = vertex_norm > 1e-12
        vertex_normals[nonzero] /= vertex_norm[nonzero, None]
        vertex_shade = np.clip(0.30 + 0.70 * np.abs(vertex_normals @ light), 0, 1)
    color = np.asarray(render.get("mesh_color_rgb", [74, 190, 167]), dtype=float)
    zbuffer = np.full((height, width), np.inf, dtype=np.float64)
    for idx in range(len(faces)):
        if not valid[idx]:
            continue
        points = projected[faces[idx]]
        x0 = max(0, int(math.floor(points[:, 0].min())))
        x1 = min(width - 1, int(math.ceil(points[:, 0].max())))
        y0 = max(0, int(math.floor(points[:, 1].min())))
        y1 = min(height - 1, int(math.ceil(points[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue
        ax, ay = points[0]; bx, by = points[1]; cx, cy = points[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denominator) < 1e-12:
            continue
        grid_y, grid_x = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px, py = grid_x + 0.5, grid_y + 0.5
        wa = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
        wb = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
        wc = 1.0 - wa - wb
        inside = (wa >= -1e-7) & (wb >= -1e-7) & (wc >= -1e-7)
        if not inside.any():
            continue
        depth = wa * tri3[idx, 0, 2] + wb * tri3[idx, 1, 2] + wc * tri3[idx, 2, 2]
        zregion = zbuffer[y0:y1 + 1, x0:x1 + 1]
        update = inside & (depth < zregion)
        if not update.any():
            continue
        zregion[update] = depth[update]
        region = image[y0:y1 + 1, x0:x1 + 1]
        if vertex_shade is None:
            rgb = np.clip(color * shade[idx], 0, 255).astype(np.uint8)
            region[update] = rgb[::-1]
        else:
            face_shade = vertex_shade[faces[idx]]
            pixel_shade = wa * face_shade[0] + wb * face_shade[1] + wc * face_shade[2]
            rgb = np.clip(pixel_shade[update, None] * color[None, :], 0, 255).astype(np.uint8)
            region[update] = rgb[:, ::-1]
    title = render.get("title")
    if title:
        cv2.putText(image, str(title), (32, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (235, 240, 245), 2, cv2.LINE_AA)
    return image, display_sampled


def scene_dir(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> Path:
    root = Path(cfg["output_root"])
    if not root.is_absolute():
        root = (config_path.parent / root).resolve()
    return root / scene["id"]


def audit_scene(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> dict[str, Any]:
    mesh = load_mesh(scene, config_path)
    report = {"scene": scene["id"], "source": mesh.provenance, "metrics": mesh_metrics(mesh), "issues": []}
    if report["metrics"]["orphan_vertex_count"]:
        report["issues"].append("mesh contains vertices unused by any face")
    extent = report["metrics"]["extent_xyz_nm"]
    if min(extent) <= 0:
        report["issues"].append("mesh has zero physical extent on at least one axis")
    out = scene_dir(cfg, scene, config_path)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mesh-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def export_scene(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> dict[str, Any]:
    mesh = load_mesh(scene, config_path)
    out = scene_dir(cfg, scene, config_path)
    path = out / "mesh.ply"
    write_ply(path, mesh)
    report = {"scene": scene["id"], "mesh": str(path), "source": mesh.provenance, "metrics": mesh_metrics(mesh)}
    (out / "mesh-export.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def storyboard_scene(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> dict[str, Any]:
    np, cv2 = _np(), _cv2()
    mesh = load_mesh(scene, config_path)
    render = dict(cfg.get("mesh_render", {})); render.update(scene.get("render", {}))
    frames, sampled = [], False
    for angle in (0, 90, 180, 270):
        frame, was_sampled = render_frame(mesh, render, angle)
        frames.append(frame); sampled |= was_sampled
    thumb_w, thumb_h = 640, 360
    sheet = np.zeros((thumb_h * 2, thumb_w * 2, 3), dtype=np.uint8)
    for i, frame in enumerate(frames):
        sheet[(i // 2) * thumb_h:(i // 2 + 1) * thumb_h, (i % 2) * thumb_w:(i % 2 + 1) * thumb_w] = cv2.resize(frame, (thumb_w, thumb_h))
    out = scene_dir(cfg, scene, config_path); out.mkdir(parents=True, exist_ok=True)
    path = out / "mesh-storyboard.jpg"
    cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    report = {"scene": scene["id"], "storyboard": str(path), "display_faces_sampled": sampled, "metrics": mesh_metrics(mesh)}
    (out / "mesh-storyboard.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def render_scene(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> dict[str, Any]:
    cv2 = _cv2()
    mesh = load_mesh(scene, config_path)
    render = dict(cfg.get("mesh_render", {})); render.update(scene.get("render", {}))
    width, height = int(render.get("width", 1280)), int(render.get("height", 720))
    fps, seconds = int(render.get("fps", 24)), float(render.get("seconds", 8.0))
    if fps <= 0 or seconds <= 0:
        raise ValueError("fps and seconds must be positive")
    frame_count = max(1, round(fps * seconds))
    out = scene_dir(cfg, scene, config_path); out.mkdir(parents=True, exist_ok=True)
    video = out / f"{scene['id']}_mesh_turntable.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*render.get("codec", "mp4v")), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer for {video}")
    frame_dir = out / "frames"
    write_frames = bool(render.get("png_frames", False))
    if write_frames:
        frame_dir.mkdir(exist_ok=True)
    sampled = False
    orbit = float(render.get("orbit_degrees", 360.0))
    for index in range(frame_count):
        frame, was_sampled = render_frame(mesh, render, orbit * index / frame_count)
        sampled |= was_sampled; writer.write(frame)
        if write_frames:
            cv2.imwrite(str(frame_dir / f"frame_{index:06d}.png"), frame)
    writer.release()
    write_ply(out / "mesh.ply", mesh)
    manifest = {
        "scene": scene["id"], "video": str(video), "mesh": str(out / "mesh.ply"),
        "width": width, "height": height, "fps": fps, "frame_count": frame_count,
        "duration_seconds": frame_count / fps, "display_faces_sampled": sampled,
        "source": mesh.provenance, "metrics": mesh_metrics(mesh), "render": render,
    }
    (out / "mesh-render.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_scene(cfg: dict[str, Any], scene: dict[str, Any], config_path: Path) -> dict[str, Any]:
    np, cv2 = _np(), _cv2()
    out = scene_dir(cfg, scene, config_path)
    manifest_path = out / "mesh-render.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"render manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    video, mesh_path = Path(manifest["video"]), Path(manifest["mesh"])
    cap = cv2.VideoCapture(str(video))
    result = {
        "scene": scene["id"], "opened": bool(cap.isOpened()),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS)), "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }
    sample_indices = np.linspace(0, max(0, result["frame_count"] - 1), 8).astype(int)
    thumbs, decoded = [], []
    for index in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index)); ok, frame = cap.read(); decoded.append(bool(ok))
        thumbs.append(cv2.resize(frame, (480, 270)) if ok else np.zeros((270, 480, 3), np.uint8))
    cap.release()
    sheet = np.zeros((540, 1920, 3), np.uint8)
    for i, frame in enumerate(thumbs):
        sheet[(i // 4) * 270:(i // 4 + 1) * 270, (i % 4) * 480:(i % 4 + 1) * 480] = frame
    contact = out / "mesh-verification-contact-sheet.jpg"
    cv2.imwrite(str(contact), sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    expected = manifest
    result.update({
        "decoded_samples": decoded, "contact_sheet": str(contact),
        "video_sha256": _sha256(video), "mesh_sha256": _sha256(mesh_path),
        "checks": {
            "dimensions": result["width"] == expected["width"] and result["height"] == expected["height"],
            "fps": abs(result["fps"] - expected["fps"]) < 0.05,
            "frame_count": result["frame_count"] == expected["frame_count"],
            "all_samples_decoded": all(decoded), "mesh_exists": mesh_path.exists(),
        },
    })
    result["ok"] = result["opened"] and all(result["checks"].values())
    (out / "mesh-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["ok"]:
        raise RuntimeError(f"mesh verification failed for {scene['id']}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "export", "storyboard", "render", "verify"))
    parser.add_argument("config", type=Path)
    parser.add_argument("--scene", action="append", dest="scenes", help="scene id; repeat to select several")
    parser.add_argument("--force", action="store_true", help="replace an existing export, storyboard, or render")
    args = parser.parse_args(argv)
    cfg = load_config(args.config.resolve())
    actions = {"audit": audit_scene, "export": export_scene, "storyboard": storyboard_scene,
               "render": render_scene, "verify": verify_scene}
    reports = []
    for scene in selected_scenes(cfg, args.scenes):
        if not args.force:
            out = scene_dir(cfg, scene, args.config.resolve())
            target = {
                "export": out / "mesh.ply",
                "storyboard": out / "mesh-storyboard.jpg",
                "render": out / f"{scene['id']}_mesh_turntable.mp4",
            }.get(args.command)
            if target is not None and target.exists():
                raise RuntimeError(f"refusing to overwrite {target}; review it and rerun with --force")
        reports.append(actions[args.command](cfg, scene, args.config.resolve()))
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
