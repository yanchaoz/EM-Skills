"""Make a small, explicitly SYNTHETIC fixture; it contains no microscopy data."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from cutaway_core import write_json


def make_demo(output):
    out = Path(output).resolve()
    targets = [out / name for name in ("synthetic.npy", "synthetic_core.obj", "project.json", "SYNTHETIC.txt")]
    if any(p.exists() for p in targets):
        raise FileExistsError("Demo outputs already exist; use a new directory")
    out.mkdir(parents=True, exist_ok=True)
    z, y, x = np.mgrid[:32, :72, :48]
    rng = np.random.default_rng(42)
    # Synthetic intensity encodes depth so a purely emissive rendering still
    # reveals its cuts. This is a test signal, not biological contrast.
    texture = 45 + 6*z + 18 * np.sin(x / 2.7 + y / 4.1) * np.cos(y / 3.3 + z / 2.9)
    texture += 5 * rng.standard_normal(texture.shape)
    texture -= 12 * (z % 4 == 0)
    raw = np.clip(texture, 20, 240).astype(np.uint8)
    raw[:, :2, :3] = 0
    np.save(targets[0], raw, allow_pickle=False)
    # Closed triangulated ellipsoid with unambiguous original-nm coordinates.
    centre = np.array([23500., 35500., 15500.])
    radius = np.array([13500., 24500., 12500.])
    rings, segments = 15, 32
    vertices = [centre + [0, 0, radius[2]]]
    for j in range(1, rings):
        theta = np.pi * j / rings
        for i in range(segments):
            phi = 2 * np.pi * i / segments
            vertices.append(centre + radius * [np.sin(theta)*np.cos(phi), np.sin(theta)*np.sin(phi), np.cos(theta)])
    vertices.append(centre - [0, 0, radius[2]])
    bottom = len(vertices)-1
    faces = []
    for i in range(segments):
        a, b = 1+i, 1+(i+1)%segments
        faces.append((0, a, b))
    for j in range(rings-2):
        for i in range(segments):
            a = 1+j*segments+i
            b = 1+j*segments+(i+1)%segments
            c, d = a+segments, b+segments
            faces.extend(((a, c, b), (b, c, d)))
    for i in range(segments):
        a = 1+(rings-2)*segments+i
        b = 1+(rings-2)*segments+(i+1)%segments
        faces.append((a, bottom, b))
    obj = ["# SYNTHETIC geometry for workflow testing only; coordinates in nm"]
    obj.extend("v %.8f %.8f %.8f" % tuple(v) for v in vertices)
    obj.extend("f %d %d %d" % tuple(i+1 for i in f) for f in faces)
    targets[1].write_text("\n".join(obj)+"\n", encoding="utf-8")
    config = dict(schema_version=1, dataset_kind="SYNTHETIC_TEST_FIXTURE_NOT_MICROSCOPY",
        source=dict(path="synthetic.npy", axis_order="zyx", voxel_size_nm_xyz=[1000, 1000, 1000],
                    offset_nm_xyz=[0, 0, 0], zero_is_missing=True),
        mesh=dict(path="synthetic_core.obj", units="nm", offset_nm_xyz=[0, 0, 0]),
        geometry=dict(reflect_z=True, basis_rotation_deg=0,
            outer_uv_bounds_um=[[1, 1], [46, 70]], display_z_bounds_um=[0, 31], keep_planes=[],
            remove_regions=[
                dict(name="first_step", planes=[dict(coeff_uvz=[1,0,0], threshold_um=12),
                    dict(coeff_uvz=[0,-1,0], threshold_um=-57), dict(coeff_uvz=[0,0,1], threshold_um=24)]),
                dict(name="second_step", planes=[dict(coeff_uvz=[1,0,0], threshold_um=17),
                    dict(coeff_uvz=[0,-1,0], threshold_um=-50), dict(coeff_uvz=[0,0,1], threshold_um=16)])]),
        display=dict(normalization=dict(mode="none", percentiles=[1,99]),
                     illumination=dict(enabled=False, target_mean=110, max_gain=4.5, downsample=8, sigma=3),
                     linear_white_mix=.08, emission_power=.85),
        camera=dict(location_mm=[.1024811268,-.0198031738,.1304066628], rotation_euler_rad=[.6853196025,.1454255283,.7844889164],
                    ortho_scale_mm=.105),
        contour=dict(mode="xray", gray_linear=1, alpha_center=.28, alpha_edge=.9, roughness=.42, emission=.35),
        render=dict(resolution=[600,600], samples=12, device="CPU", tile_size=128, density_per_mm=1500, step_um=.5),
        output_dir="outputs")
    write_json(targets[2], config)
    targets[3].write_text("SYNTHETIC TEST FIXTURE. Not biological data or a reconstruction of real tissue.\n"
                          "The uint8 volume contains mathematical pseudo-texture, an artificial Z-intensity gradient,\n"
                          "and every-four-layer intensity markers; the OBJ is an ellipsoid.\n",
                          encoding="utf-8")
    return targets[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(make_demo(args.out))


if __name__ == "__main__":
    main()
