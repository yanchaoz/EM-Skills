"""Stream accepted aligned intensities to lossless TIFF / XY-only precomputed."""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from registration_common import digest_file, iter_result, load_result, pixel_hash, resolve, write_json


def xy_downsample(a):
    if a.shape[0] % 2 or a.shape[1] % 2:
        raise ValueError("Pad a derived canvas with a recorded origin before downsampling odd dimensions")
    mean = a.astype(np.float64).reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean(axis=(1, 3))
    if a.dtype.kind in "ui":
        mean = np.floor(mean + 0.5)
    return mean.astype(a.dtype)


def export(result, output, tiff=False, cloudvolume=False, mips=1):
    source, cfg = load_result(result)
    out = Path(output).resolve()
    if not tiff and not cloudvolume:
        raise ValueError("Select --tiff and/or --cloudvolume explicitly")
    if not isinstance(mips, int) or not 1 <= mips <= 12:
        raise ValueError("mips must be between 1 and 12")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use a new empty export directory; completed artifacts are not overwritten")
    for section in cfg["sections"]:
        if "path" in section:
            p = resolve(source.parent, section["path"])
            if p == out or out in p.parents:
                raise ValueError("Export would contain a source image")
    if cfg.get("cloudvolume", "").startswith("file://"):
        cv_source = Path(cfg["cloudvolume"][7:]).resolve()
        if cv_source == out or out in cv_source.parents or cv_source in out.parents:
            raise ValueError("Source and destination precomputed directories overlap")
    if cfg["dtype"] not in ("uint8", "uint16", "float32"):
        raise ValueError("This exporter supports uint8, uint16 and float32 intensities")
    factor = 2 ** (mips - 1)
    if cloudvolume and any(v % factor for v in cfg["shape_zyx"][1:] + cfg["voxel_offset_xyz"][:2]):
        raise ValueError("XY shape and origin must align to the coarsest grid; pad with recorded bounds or use fewer mips")
    # Resolve optional dependencies before creating any output.
    if tiff:
        import tifffile
    if cloudvolume:
        from cloudvolume import CloudVolume
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "export-status.json", {"status": "in_progress", "source_manifest_sha256": digest_file(source)})
    cvs = []
    if cloudvolume:
        url = "file://" + str(out / "image")
        info = CloudVolume.create_new_info(num_channels=1, layer_type="image", data_type=cfg["dtype"], encoding="raw", resolution=cfg["voxel_size_nm_xyz"], voxel_offset=cfg["voxel_offset_xyz"], volume_size=cfg["shape_zyx"][::-1], chunk_size=[512, 512, 1])
        cv = CloudVolume(url, info=info, compress=True, progress=False)
        for mip in range(1, mips):
            cv.add_scale((2**mip, 2**mip, 1), chunk_size=[512, 512, 1])
        cv.commit_info()
        cvs = [CloudVolume(url, mip=m, compress=True, fill_missing=False, progress=False, parallel=1) for m in range(mips)]
    records = []
    for section, a in iter_result(source):
        rec = {"id": section["id"], "z_index": section["z_index"], "sha256_pixels": pixel_hash(a)}
        if tiff:
            dest = out / "tiff" / f"layer{section['z_index'] + 1:06d}.tif"
            dest.parent.mkdir(exist_ok=True)
            temporary = dest.with_suffix(".partial.tif")
            rx, ry, rz = cfg["voxel_size_nm_xyz"]
            metadata = {"axes": "YX", "voxel_size_nm_xyz": [rx, ry, rz], "voxel_offset_xyz": cfg["voxel_offset_xyz"], "section_id": section["id"], "z_index": section["z_index"], "z_position_nm": (cfg["voxel_offset_xyz"][2] + section["z_index"]) * rz}
            tifffile.imwrite(temporary, a, photometric="minisblack", compression="deflate", compressionargs={"level": 1}, resolution=(1e7 / rx, 1e7 / ry), resolutionunit="CENTIMETER", metadata=metadata)
            with tifffile.TiffFile(temporary) as handle:
                back = handle.asarray()
                if pixel_hash(back) != rec["sha256_pixels"] or back.dtype != a.dtype or back.shape != a.shape:
                    raise ValueError("TIFF complete-plane readback mismatch")
                for tag, wanted in (("XResolution", 1e7 / rx), ("YResolution", 1e7 / ry)):
                    n, d = handle.pages[0].tags[tag].value
                    if not np.isclose(n / d, wanted, rtol=1e-7):
                        raise ValueError("TIFF physical-resolution tag mismatch")
            temporary.replace(dest)
            rec["tiff"] = {"path": str(dest), "bytes": dest.stat().st_size, "sha256": digest_file(dest)}
        pyramid = a
        rec["mips"] = []
        for mip, cv in enumerate(cvs):
            if mip:
                pyramid = xy_downsample(pyramid)
            z = cfg["voxel_offset_xyz"][2] + section["z_index"]
            cv[:, :, z:z + 1] = np.asfortranarray(pyramid.T[:, :, None, None])
            back = np.asarray(cv[:, :, z:z + 1])[:, :, 0, 0].T
            if pixel_hash(back) != pixel_hash(pyramid):
                raise ValueError(f"Complete mip{mip} plane readback mismatch")
            scale = cv.info["scales"][mip]
            if scale["resolution"] != [cfg["voxel_size_nm_xyz"][0] * 2**mip, cfg["voxel_size_nm_xyz"][1] * 2**mip, cfg["voxel_size_nm_xyz"][2]] or scale["size"][2] != cfg["shape_zyx"][0] or scale["voxel_offset"][2] != cfg["voxel_offset_xyz"][2]:
                raise ValueError("Pyramid changed the Z grid")
            rec["mips"].append({"mip": mip, "sha256_pixels": pixel_hash(pyramid), "shape_yx": list(pyramid.shape)})
        records.append(rec)
        write_json(out / "checks" / f"{section['z_index']:06d}.json", rec)
    report = {"status": "PASS", "scope": "Pixel-preserving conversion of provided aligned data; no registration accuracy inferred", "source_manifest_sha256": digest_file(source), "shape_zyx": cfg["shape_zyx"], "voxel_size_nm_xyz": cfg["voxel_size_nm_xyz"], "voxel_offset_xyz": cfg["voxel_offset_xyz"], "full_planes_verified": len(records), "mips_verified": len(cvs), "sections": records}
    write_json(out / "verification.json", report)
    write_json(out / "export-status.json", {"status": "complete", "planes": len(records)})
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("result")
    p.add_argument("--output", required=True)
    p.add_argument("--tiff", action="store_true")
    p.add_argument("--cloudvolume", action="store_true")
    p.add_argument("--mips", type=int, default=1)
    a = p.parse_args()
    report = export(a.result, a.output, a.tiff, a.cloudvolume, a.mips)
    print(f"PASS: {report['full_planes_verified']} complete planes; {report['mips_verified']} CloudVolume levels")
