# Mesh contract

## Supported sources

### Existing precomputed mesh

Use `source.type: precomputed` with a pinned precomputed segmentation URI and explicit `segment_ids`. `cloudvolume_mesh.py` calls `CloudVolume.mesh.get(..., fuse=True)`. Set `coordinates` to `nm` unless the source is known to return voxel coordinates; voxel coordinates additionally require verified `resolution_nm_xyz` and `voxel_offset_xyz` when CloudVolume metadata are insufficient.

### Bounded label ROI

Use `source.type: labels` for a 3D `.npy`, `.npz`, or TIFF label volume. Required fields are `axes: zyx`, `segment_ids`, `roi_zyx=[z0,z1,y0,y1,x0,x1]`, and `resolution_nm_zyx`. `voxel_offset_zyx` defaults to zero. Marching cubes runs only on the requested ROI and exports physical XYZ coordinates in nm.

Do not run unbounded marching cubes over a large volume. Do not interpret a one-slice mask as a biological 3D surface.

### Existing file

Use `source.type: file` and `path`. `.npz` must contain `vertices` and `faces`; PLY/OBJ and other mesh formats require `trimesh`. The Skill assumes file vertices already use the units documented by the project.

## Rendering and export

The exported ASCII PLY is complete. If `face_count > max_render_faces`, the renderer fails closed and asks for a display LOD/decimated mesh. Explicit `allow_face_sampling: true` enables a deterministic last-resort preview that may contain holes; it is recorded as `display_faces_sampled` and never changes the PLY. Sampling is not geometric simplification or scientific measurement.

The renderer produces a four-angle storyboard or an MP4 turntable without OpenGL. Use a real mesh viewer for interactive inspection and advanced transparency. A 2D `.ngvideo` handoff may expose segmentation objects with `object_alpha`, but its appearance depends on mesh metadata being available to Neuroglancer.

## Required provenance

Preserve source type, URI/path, segment IDs, mip, coordinate convention, ROI, resolution, voxel offset, vertex/face counts, physical bounds, render configuration, output hashes, and any display face sampling.
