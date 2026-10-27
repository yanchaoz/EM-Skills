"""Render a prepared native-grid EM cache from a new Blender scene.

Run with Blender 4.5 LTS (not system Python)::
  blender --background --python scripts/render_blender.py -- \
    --config project.json --cache prepared/volume.vdb --output renders

Nothing is installed, preferences are never saved, and source data are read-only.
This module can also be imported without Blender for contract tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
import traceback


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def native_transform(source, shape_zyx, reflect_z):
    """Native IJK VDB -> world mm; reflection preserves physical voxel spacing."""
    spacing = source["voxel_size_nm_xyz"]
    offset = source.get("offset_nm_xyz", [0, 0, 0])
    nz = shape_zyx[0]
    pivot_nm = 2 * offset[2] + (nz - 1) * spacing[2]
    location = [value / 1e6 for value in offset]
    scale = [value / 1e6 for value in spacing]
    if reflect_z:
        scale[2] = -scale[2]
        location[2] = (offset[2] + (nz - 1) * spacing[2]) / 1e6
    return {"volume_scale_xyz": scale, "volume_location_mm": location,
            "reflect_z": reflect_z, "reflection_pivot_nm": pivot_nm}


def read_obj(path, units, offset_nm_xyz, reflect_z, pivot_nm):
    """Read source topology without applying modifiers, smoothing or remeshing."""
    unit_mm = {"nm": 1e-6, "um": 1e-3, "mm": 1.0}[units]
    vertices, faces = [], []
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            fields = line.partition("#")[0].split()
            if not fields:
                continue
            if fields[0] == "v":
                if len(fields) < 4:
                    raise ValueError(f"OBJ line {line_number}: vertex has fewer than 3 coordinates")
                xyz = [float(fields[i + 1]) * unit_mm + offset_nm_xyz[i] / 1e6
                       for i in range(3)]
                if not all(math.isfinite(v) for v in xyz):
                    raise ValueError(f"OBJ line {line_number}: non-finite coordinate")
                if reflect_z:
                    xyz[2] = pivot_nm / 1e6 - xyz[2]
                vertices.append(xyz)
            elif fields[0] == "f":
                face = []
                for token in fields[1:]:
                    index = int(token.split("/")[0])
                    if index == 0:
                        raise ValueError(f"OBJ line {line_number}: zero vertex index")
                    face.append(index - 1 if index > 0 else len(vertices) + index)
                if len(face) < 3 or any(i < 0 or i >= len(vertices) for i in face):
                    raise ValueError(f"OBJ line {line_number}: invalid face indices")
                faces.append(list(reversed(face)) if reflect_z else face)
    if not vertices or not faces:
        raise ValueError("Contour OBJ must contain vertices and polygon faces")
    payload = json.dumps({"vertices_mm": vertices, "faces": faces}, separators=(",", ":"))
    return vertices, faces, hashlib.sha256(payload.encode()).hexdigest()


def validate_cache(cfg, cache_path):
    cache_path = Path(cache_path).resolve()
    manifest_path = cache_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported prepared manifest schema_version")
    verification = manifest.get("verification", {})
    if verification.get("status") != "passed" or verification.get("source_data_modified") is not False:
        raise ValueError("Prepared cache does not have a passed, unmodified-source verification")
    shape = manifest["source"].get("shape_zyx", [])
    if (len(shape) != 3 or any(not isinstance(n, int) or n <= 0 for n in shape)
            or manifest["source"].get("dtype") != "uint8"):
        raise ValueError("Prepared source must have a valid positive 3D uint8 shape")
    cache = manifest["vdb"]
    if cache.get("transform") != "native_index_unit_voxel" or cache.get("grid_voxel_size") != [1, 1, 1]:
        raise ValueError("Cache must use native IJK grid coordinates with a unit VDB transform")
    if cache.get("geometry_pruned") is not False:
        raise ValueError("Renderer requires an unpruned native cache; prepare it again")
    if not {"em_linear", "em_support"}.issubset(cache.get("grids", [])):
        raise ValueError("Cache must contain em_linear and em_support grids")
    checks = {}
    for name in ("source", "mesh"):
        current = cfg[name]
        prepared = manifest[name]
        actual = sha256(current["path"])
        if actual != prepared["sha256"]:
            raise ValueError(f"{name} changed since preparation; prepare a new cache")
        checks[name] = {"path": str(current["path"]), "sha256": actual}
    for key in ("axis_order", "voxel_size_nm_xyz", "offset_nm_xyz", "zero_is_missing"):
        default = [0, 0, 0] if key == "offset_nm_xyz" else None
        if cfg["source"].get(key, default) != manifest["source"].get(key, default):
            raise ValueError(f"source.{key} differs from the prepared cache")
    for key in ("normalization", "illumination"):
        if cfg.get("display", {}).get(key) != manifest.get("display", {}).get(key):
            raise ValueError(f"display.{key} differs from the prepared cache")
    actual_cache = sha256(cache_path)
    if actual_cache != cache["sha256"]:
        raise ValueError("VDB checksum differs from the prepared manifest")
    checks["cache"] = {"path": str(cache_path), "sha256": actual_cache}
    checks["prepared_manifest"] = {"path": str(manifest_path), "sha256": sha256(manifest_path)}
    return manifest, checks


def validate_render_config(cfg):
    """Require an explicit camera and reject invalid display/render parameters early."""
    if not cfg.get("mesh"):
        raise ValueError("Rendering requires mesh.path, mesh.units and an original OBJ contour")
    camera = cfg.get("camera", {})
    for key in ("location_mm", "rotation_euler_rad"):
        values = camera.get(key, [])
        if len(values) != 3 or not all(math.isfinite(float(v)) for v in values):
            raise ValueError(f"camera.{key} must explicitly contain three finite values")
    scale = float(camera.get("ortho_scale_mm", 0))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("camera.ortho_scale_mm must be explicit, finite and positive")
    render = cfg.setdefault("render", {})
    resolution = render.get("resolution", [1000, 1000])
    if len(resolution) != 2 or any(not isinstance(v, int) or isinstance(v, bool) or v <= 0 for v in resolution):
        raise ValueError("render.resolution must contain two positive integers")
    for key, default in (("samples", 16), ("tile_size", 128), ("max_volume_steps", 4096)):
        value = render.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"render.{key} must be a positive integer")
    for key in ("density_per_mm", "step_um"):
        if key in render and (not math.isfinite(float(render[key])) or render[key] <= 0):
            raise ValueError(f"render.{key} must be finite and positive")
    if render.get("device", "CPU") not in ("CPU", "CUDA", "OPTIX"):
        raise ValueError("render.device must be CPU, CUDA or OPTIX")
    cfg.setdefault("geometry", {})
    contour = cfg.setdefault("contour", {})
    if contour.get("mode", "xray") not in ("xray", "occluded"):
        raise ValueError("contour.mode must be xray or occluded")
    for key, default in (("gray_linear", 1.), ("alpha_center", .28), ("alpha_edge", .90), ("roughness", .42)):
        value = float(contour.get(key, default))
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"contour.{key} must be finite and between 0 and 1")
    emission = float(contour.get("emission", .35))
    if not math.isfinite(emission) or emission < 0:
        raise ValueError("contour.emission must be finite and nonnegative")
    display = cfg.get("display", {})
    mix, power = float(display.get("linear_white_mix", .08)), float(display.get("emission_power", .85))
    if not math.isfinite(mix) or not 0 <= mix < 1 or not math.isfinite(power) or power <= 0:
        raise ValueError("Invalid display linear_white_mix or emission_power")


def reserve_output(path, overwrite, inputs=()):
    path = Path(path).resolve()
    if path.exists() and not path.is_dir():
        raise ValueError("Output path exists and is not a directory")
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise FileExistsError("Output directory is not empty; use a new directory or explicit --overwrite")
    names = ["render.png", "transparent.png", "em_only.png", "contour_only.png",
             "transparent_0001.png", "em_only_0001.png", "contour_only_0001.png",
             "scene.blend", "scene.blend1", "render_manifest.json"]
    input_paths = {Path(item).resolve() for item in inputs}
    if any((path / name).resolve() in input_paths for name in names):
        raise ValueError("An output would overwrite an input; choose another output directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def math_node(nodes, links, operation, a, b):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    for index, value in enumerate((a, b)):
        if isinstance(value, (float, int)):
            node.inputs[index].default_value = value
        else:
            links.new(value, node.inputs[index])
    return node.outputs[0]


def clip_mask(geometry, axes, m):
    """Inclusive keep bounds, strict removal planes; m builds nodes or evaluates numbers."""
    inside = 1.0
    if "outer_uv_bounds_um" in geometry:
        bounds = geometry["outer_uv_bounds_um"]
        for axis, lo, hi in zip(axes[:2], bounds[0], bounds[1]):
            inside = m("MULTIPLY", inside, m("SUBTRACT", 1., m("LESS_THAN", axis, lo)))
            inside = m("MULTIPLY", inside, m("SUBTRACT", 1., m("GREATER_THAN", axis, hi)))
    if "display_z_bounds_um" in geometry:
        lo, hi = geometry["display_z_bounds_um"]
        inside = m("MULTIPLY", inside, m("SUBTRACT", 1., m("LESS_THAN", axes[2], lo)))
        inside = m("MULTIPLY", inside, m("SUBTRACT", 1., m("GREATER_THAN", axes[2], hi)))
    def halfspace(plane, inclusive=False):
        total = 0.0
        for coefficient, axis in zip(plane["coeff_uvz"], axes):
            total = m("ADD", total, m("MULTIPLY", axis, coefficient))
        if inclusive:
            return m("SUBTRACT", 1., m("LESS_THAN", total, plane["threshold_um"]))
        return m("GREATER_THAN", total, plane["threshold_um"])
    for plane in geometry.get("keep_planes", []):
        keep = halfspace(plane, inclusive=True)
        if "only_below_v_um" in plane:
            exempt = m("SUBTRACT", 1., m("LESS_THAN", axes[1], plane["only_below_v_um"]))
            keep = m("MAXIMUM", keep, exempt)
        inside = m("MULTIPLY", inside, keep)
    removed = 0.0
    for region in geometry.get("remove_regions", []):
        member = 1.0
        for plane in region["planes"]:
            member = m("MULTIPLY", member, halfspace(plane))
        removed = m("MAXIMUM", removed, member)
    return m("MULTIPLY", inside, m("SUBTRACT", 1., removed))


def make_volume_material(bpy, cfg, source, shape):
    material = bpy.data.materials.new("Native EM display transfer and analytical cutaway")
    material.use_nodes = True
    material.cycles.volume_interpolation = "LINEAR"
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    position = nodes.new("ShaderNodeNewGeometry")
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    links.new(position.outputs["Position"], xyz.inputs[0])
    mm_axes = [xyz.outputs[key] for key in ("X", "Y", "Z")]
    world = [math_node(nodes, links, "MULTIPLY", value, 1000.) for value in mm_axes]
    theta = math.radians(cfg["geometry"].get("basis_rotation_deg", 0))
    c, s = math.cos(theta), math.sin(theta)
    m = lambda operation, a, b: math_node(nodes, links, operation, a, b)
    axes = [m("ADD", m("MULTIPLY", world[0], c), m("MULTIPLY", world[1], s)),
            m("ADD", m("MULTIPLY", world[0], -s), m("MULTIPLY", world[1], c)), world[2]]
    inside = clip_mask(cfg.get("geometry", {}), axes, m)
    # Exact native voxel faces prevent interpolation from inventing exterior support.
    for axis, offset, spacing, count in zip(world, source["offset_nm_xyz"],
                                            source["voxel_size_nm_xyz"], reversed(shape)):
        lo = (offset - .5 * spacing) / 1000
        hi = (offset + (count - .5) * spacing) / 1000
        inside = m("MULTIPLY", inside, m("GREATER_THAN", axis, lo))
        inside = m("MULTIPLY", inside, m("LESS_THAN", axis, hi))
    support = nodes.new("ShaderNodeAttribute")
    support.attribute_type, support.attribute_name = "GEOMETRY", "em_support"
    occupied = m("GREATER_THAN", support.outputs["Fac"], .5)
    density = m("MULTIPLY", m("MULTIPLY", occupied, inside), cfg["render"].get("density_per_mm", 1500))
    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_type, attr.attribute_name = "GEOMETRY", "em_linear"
    display = cfg.get("display", {})
    mix = display.get("linear_white_mix", .08)
    power = display.get("emission_power", .85)
    if not 0 <= mix < 1 or power <= 0:
        raise ValueError("Require 0 <= display.linear_white_mix < 1 and positive emission_power")
    color = m("POWER", m("ADD", m("MULTIPLY", attr.outputs["Fac"], 1 - mix), mix), power)
    absorb = nodes.new("ShaderNodeVolumeAbsorption")
    absorb.inputs["Color"].default_value = (0, 0, 0, 1)
    links.new(density, absorb.inputs["Density"])
    emission = nodes.new("ShaderNodeEmission")
    links.new(color, emission.inputs["Color"])
    links.new(density, emission.inputs["Strength"])
    add = nodes.new("ShaderNodeAddShader")
    links.new(absorb.outputs[0], add.inputs[0])
    links.new(emission.outputs[0], add.inputs[1])
    links.new(add.outputs[0], output.inputs["Volume"])
    return material


def make_contour_material(bpy, cfg):
    material = bpy.data.materials.new("Full original contour - neutral translucent surface")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    surface = nodes.new("ShaderNodeBsdfPrincipled")
    gray = cfg.get("gray_linear", 1.0)
    surface.inputs["Base Color"].default_value = (gray, gray, gray, 1)
    surface.inputs["Roughness"].default_value = cfg.get("roughness", .42)
    surface.inputs["Specular IOR Level"].default_value = .22
    surface.inputs["Emission Color"].default_value = (1, 1, 1, 1)
    surface.inputs["Emission Strength"].default_value = cfg.get("emission", .35)
    fresnel = nodes.new("ShaderNodeFresnel")
    fresnel.inputs["IOR"].default_value = 1.45
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (cfg.get("alpha_center", .28),) * 3 + (1,)
    ramp.color_ramp.elements[1].color = (cfg.get("alpha_edge", .90),) * 3 + (1,)
    links.new(fresnel.outputs["Fac"], ramp.inputs["Fac"])
    geometry = nodes.new("ShaderNodeNewGeometry")
    front = math_node(nodes, links, "SUBTRACT", 1., geometry.outputs["Backfacing"])
    alpha = math_node(nodes, links, "MULTIPLY", front, ramp.outputs["Color"])
    mix = nodes.new("ShaderNodeMixShader")
    links.new(alpha, mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(surface.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    return material


def configure_device(bpy, scene, requested):
    """Select only the requested backend for this process; never persist preferences."""
    if requested == "CPU":
        scene.cycles.device = "CPU"
        return ["CPU"]
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = requested
        prefs.get_devices()
    except Exception as error:
        raise RuntimeError(f"Requested {requested} backend is unavailable; no fallback was used") from error
    selected = [item for item in prefs.devices if item.type == requested]
    if not selected:
        raise RuntimeError(f"No {requested} device found; explicitly choose --device CPU if desired")
    for item in prefs.devices:
        item.use = item.type == requested
    scene.cycles.device = "GPU"
    return [item.name for item in selected]


def build_scene(bpy, cfg, prepared, cache_path, output, args):
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = .001  # One scene unit is one millimetre.
    settings = cfg["render"]
    resolution = [args.size, args.size] if args.size else settings.get("resolution", [1000, 1000])
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.cycles.samples = args.samples or settings.get("samples", 16)
    scene.cycles.use_denoising = True
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = .008
    scene.cycles.transparent_max_bounces = 32
    scene.cycles.volume_bounces = 0
    scene.cycles.volume_step_rate = 1.
    scene.cycles.volume_max_steps = settings.get("max_volume_steps", 4096)
    scene.cycles.use_auto_tile = True
    scene.cycles.tile_size = settings.get("tile_size", 128)
    requested = args.device or settings.get("device", "CPU")
    devices = configure_device(bpy, scene, requested)
    collections = {}
    for name in ("EM", "Contour", "Rig"):
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        collections[name] = collection
    source = prepared["source"]
    shape = source["shape_zyx"]
    transform = native_transform(source, shape, cfg["geometry"].get("reflect_z", False))
    volume_data = bpy.data.volumes.new("Native EM grids")
    volume_data.filepath = str(cache_path)
    volume = bpy.data.objects.new("Original native-grid EM", volume_data)
    collections["EM"].objects.link(volume)
    volume.scale, volume.location = transform["volume_scale_xyz"], transform["volume_location_mm"]
    if not volume_data.grids.load():
        raise RuntimeError(volume_data.grids.error_message)
    if not {"em_linear", "em_support"}.issubset({grid.name for grid in volume_data.grids}):
        raise ValueError("Actual VDB lacks required grids")
    volume_data.render.precision = "FULL"
    volume_data.render.clipping = 0
    # Essential with an index-space VDB: density and sample distance are in world mm,
    # not multiplied again by the native-voxel object scale (Blender defaults OBJECT).
    volume_data.render.space = "WORLD"
    volume_data.render.step_size = settings.get("step_um", min(source["voxel_size_nm_xyz"]) / 2000) / 1000
    volume_data.materials.append(make_volume_material(bpy, cfg, source, shape))
    mesh_cfg = cfg["mesh"]
    vertices, faces, geometry_hash = read_obj(mesh_cfg["path"], mesh_cfg["units"],
        mesh_cfg.get("offset_nm_xyz", [0, 0, 0]), transform["reflect_z"], transform["reflection_pivot_nm"])
    mesh_data = bpy.data.meshes.new("Original OBJ topology - no modifiers")
    mesh_data.from_pydata(vertices, [], faces)
    mesh_data.update()
    # Smooth lighting normals only: the vertices, faces and physical geometry stay unchanged.
    for face in mesh_data.polygons:
        face.use_smooth = True
    mesh = bpy.data.objects.new("Complete original contour", mesh_data)
    collections["Contour"].objects.link(mesh)
    mesh.visible_shadow = False
    mesh_data.materials.append(make_contour_material(bpy, cfg.get("contour", {})))
    camera_cfg = cfg["camera"]
    camera_data = bpy.data.cameras.new("Explicit reproducible orthographic camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    collections["Rig"].objects.link(camera)
    camera.location, camera.rotation_euler = camera_cfg["location_mm"], camera_cfg["rotation_euler_rad"]
    camera_data.type, camera_data.ortho_scale = "ORTHO", camera_cfg["ortho_scale_mm"]
    extent = [n * size / 1e6 for n, size in zip(reversed(shape), source["voxel_size_nm_xyz"])]
    span = max(extent)
    center = Vector([(offset + (n - 1) * size / 2) / 1e6 for offset, n, size in
                     zip(source["offset_nm_xyz"], reversed(shape), source["voxel_size_nm_xyz"])])
    camera_data.clip_start, camera_data.clip_end = max(span / 1e5, 1e-8), max((camera.location - center).length + 10 * span, 1)
    scene.camera = camera
    scene.world = bpy.data.worlds.new("Neutral soft world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = .15
    lighting = []
    for name, relative, power, diameter in [("Soft key", (-1, -1.3, 2), 20, 2),
                                             ("Soft fill", (2, .2, 1.3), 3, 1.5)]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.shape, data.size = power * span ** 2, "DISK", diameter * span
        light = bpy.data.objects.new(name, data)
        collections["Rig"].objects.link(light)
        light.location = center + Vector(relative) * span
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        lighting.append({"name": name, "location_mm": list(light.location), "energy": data.energy, "size_mm": data.size})
    scene.view_layers[0].name = "EM"
    scene.view_layers["EM"].layer_collection.children["Contour"].exclude = True
    contour_layer = scene.view_layers.new("Contour")
    contour_layer.layer_collection.children["EM"].exclude = True
    mode = cfg.get("contour", {}).get("mode", "xray")
    if mode not in ("xray", "occluded"):
        raise ValueError("contour.mode must be xray or occluded")
    if mode == "occluded":
        scene.view_layers.new("Combined")
    scene.use_nodes = True
    nodes, links = scene.node_tree.nodes, scene.node_tree.links
    nodes.clear()
    def layer(name):
        node = nodes.new("CompositorNodeRLayers")
        node.layer = name
        return node.outputs["Image"]
    def over(back, front):
        node = nodes.new("CompositorNodeAlphaOver")
        node.inputs[0].default_value = 1
        if isinstance(back, tuple):
            node.inputs[1].default_value = back
        else:
            links.new(back, node.inputs[1])
        links.new(front, node.inputs[2])
        return node.outputs[0]
    em_image, contour_image = layer("EM"), layer("Contour")
    combined = over(em_image, contour_image) if mode == "xray" else layer("Combined")
    composite = nodes.new("CompositorNodeComposite")
    links.new(over((1, 1, 1, 1), combined), composite.inputs[0])
    for name, socket in [("transparent", combined), ("em_only", over((1, 1, 1, 1), em_image)),
                         ("contour_only", contour_image)]:
        node = nodes.new("CompositorNodeOutputFile")
        node.base_path = str(output)
        node.format.file_format, node.format.color_mode = "PNG", "RGBA"
        node.file_slots[0].path = name + "_"
        links.new(socket, node.inputs[0])
    scene.frame_set(1)
    scene.render.filepath = str(output / "render.png")
    frame = camera_data.view_frame(scene=scene)
    projection = {"type": "ORTHO", "world_screen_width_mm": max(v.x for v in frame) - min(v.x for v in frame),
                  "world_screen_height_mm": max(v.y for v in frame) - min(v.y for v in frame),
                  "pixel_aspect_xy": [scene.render.pixel_aspect_x, scene.render.pixel_aspect_y],
                  "method": "Camera.view_frame(scene): local camera-plane span; object scale is identity"}
    return scene, {"transform": transform, "camera": camera_cfg,
        "camera_projection": projection,
        "geometry": cfg["geometry"], "display": cfg.get("display", {}),
        "contour": cfg.get("contour", {}), "mesh_vertices": len(vertices), "mesh_faces": len(faces),
        "display_mesh_geometry_sha256": geometry_hash, "mesh_clipped": False,
        "geometry_warped": False, "inpainting": False, "mesh_modifiers": [],
        "normal_shading": "smooth lighting normals only, unchanged source vertices and faces",
        "render": {**settings, "resolution": resolution, "samples": scene.cycles.samples,
                   "requested_device": requested, "actual_devices": devices,
                   "actual_step_mm": volume_data.render.step_size,
                   "volume_sampling_space": volume_data.render.space, "volume_interpolation": "LINEAR"},
        "lighting": lighting, "world_strength": .15, "view_transform": "Standard",
        "interpretation": "Scientific display, not segmentation validation; X-ray mode reveals the complete contour through EM."}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--cache", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--size", type=int)
    p.add_argument("--samples", type=int)
    p.add_argument("--device", choices=("CPU", "CUDA", "OPTIX"))
    p.add_argument("--save-blend", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    return p


def main(argv=None):
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parser().parse_args(argv)
    if args.size is not None and args.size <= 0 or args.samples is not None and args.samples <= 0:
        raise ValueError("--size and --samples must be positive")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cutaway_core import load_config, validate_config
    cfg = load_config(args.config)
    validate_config(cfg)
    validate_render_config(cfg)
    cache = args.cache.resolve()
    prepared, input_checks = validate_cache(cfg, cache)
    output = reserve_output(args.output, args.overwrite,
        [args.config, cache, cache.parent / "manifest.json", cfg["source"]["path"], cfg["mesh"]["path"]])
    import bpy
    started = time.time()
    manifest = {"schema_version": 1, "status": "started", "completed": False,
                "dataset_kind": cfg.get("dataset_kind", "user_supplied_not_independently_validated"),
                "config": {"path": str(args.config.resolve()), "sha256": sha256(args.config)},
                "inputs": input_checks, "engine": "Blender Cycles", "blender_version": bpy.app.version_string,
                "source_data_modified": False, "preferences_saved": False}
    manifest_path = output / "render_manifest.json"
    try:
        scene, details = build_scene(bpy, cfg, prepared, cache, output, args)
        manifest.update(details)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        bpy.ops.render.render(write_still=True)
        for name in ("transparent", "em_only", "contour_only"):
            emitted = output / (name + "_0001.png")
            if not emitted.is_file():
                raise RuntimeError(f"Expected compositor output missing: {emitted}")
            emitted.replace(output / (name + ".png"))
        files = [output / (name + ".png") for name in ("render", "transparent", "em_only", "contour_only")]
        dimensions = {}
        for path in files:
            with path.open("rb") as stream:
                header = stream.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError(f"Invalid PNG output: {path}")
            dimensions[path.name] = list(struct.unpack(">II", header[16:24]))
            if dimensions[path.name] != manifest["render"]["resolution"]:
                raise RuntimeError(f"Unexpected render dimensions: {path}")
        for name in ("source", "mesh"):
            if sha256(input_checks[name]["path"]) != input_checks[name]["sha256"]:
                raise RuntimeError(f"{name} changed during rendering; refusing completed manifest")
        manifest["verification"] = {"png_dimensions": dimensions,
                                    "source_and_mesh_hashes_rechecked_after_render": True,
                                    "scope": "File provenance and render contracts; biological accuracy requires separate review"}
        if args.save_blend:
            scene["Scientific rendering manifest"] = json.dumps(manifest)
            bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"), compress=True, relative_remap=False)
            files.append(output / "scene.blend")
        manifest["outputs"] = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in files]
        manifest.update(status="complete", completed=True, elapsed_seconds=time.time() - started)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("RENDER_COMPLETE", str(output / "render.png"), flush=True)
    except Exception as error:
        manifest.update(status="failed", completed=False, elapsed_seconds=time.time() - started,
                        error=str(error), traceback=traceback.format_exc())
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
