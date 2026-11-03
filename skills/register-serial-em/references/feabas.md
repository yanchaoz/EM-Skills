# Yuelong Wu / FEABAS

Official [repository](https://github.com/YuelongWu/feabas) and
[project page](https://lichtman.rc.fas.harvard.edu/feabas/).
Finite-Element Assisted Brain Assembly System, MIT license. Pin upstreams.json's
revision; follow its dependency instructions. The inspected README reports testing
with Python 3.12.2. Keep an isolated environment and record actual versions.

## Prepare one independent stack

Copy **all official configs** into an isolated run's configs directory, then set
general_configs.yaml working_directory, full_resolution (native XY nm),
section_thickness (Z nm), CPU counts and output locations. The config loader checks
cwd/configs, then parent/configs, before installed-repository defaults; run absolute
upstream scripts with cwd at this isolated workspace. Copying only general config
would omit defaults resolved from the same config directory.

Provide section_order.txt explicitly. Alphabetic order is unsafe for layer1,
layer10, layer2. For tiled sections, stitch_coord TSV headers are:

```text
{ROOT_DIR}	/data/raw/section0001
{RESOLUTION}	5.0
{TILE_SIZE}	4096	4096
tile0001.tif	0	0
tile0002.tif	3500	0
```

TILE_SIZE is height then width; tile locations are X/Y pixels; resolution is nm.
The example values are not inferred from any real dataset. Verify the source
loader against actual native images before fine rendering.

Run the pinned upstream scripts with appropriate configs:

```bash
python /code/feabas/scripts/stitch_main.py --mode matching
python /code/feabas/scripts/stitch_main.py --mode optimization
python /code/feabas/scripts/stitch_main.py --mode rendering
python /code/feabas/scripts/thumbnail_main.py --mode downsample
python /code/feabas/scripts/thumbnail_main.py --mode match
python /code/feabas/scripts/thumbnail_main.py --mode optimization
python /code/feabas/scripts/thumbnail_main.py --mode render
python /code/feabas/scripts/align_main.py --mode meshing
python /code/feabas/scripts/align_main.py --mode matching
python /code/feabas/scripts/align_main.py --mode optimization
python /code/feabas/scripts/align_main.py --mode rendering
```

For a preassembled one-tile-per-section stack, the documented thumbnail shortcut
can skip tile stitching, but the fine-stage loader still must point to native
intensities. Thumbnail-only output is not native registration.
Use the exact supported mode spellings above; thumbnail modes differ from align.

## Masks, optimization and delivery

Material masks use **black for data and white for excluded regions** in the
documented simple mask convention. A generic positive-valid mask from this skill
must be converted explicitly; do not reuse it without polarity conversion.
Provide same geometry/scale as the configured mask_mip_level. All-black is valid
only when the whole plane is valid. Tears/disconnected pieces need corresponding
materials/components rather than forcing one continuous sheet across the gap.

Choose matching working_mip_level, mesh spacing and regularization from the physical
scale and pilot residuals. Preserve native meshes, matches, outlier decisions and
convergence diagnostics. Native caches skip existing files: new settings require a
new run or deliberate invalidation, never silent reuse.

Rendering defaults can shift origin: `rendering.offset_bbox: true` normalizes the
canvas. Record that transform or set false to retain world origin. Set mip_level=0,
verify native loaders, and disable matching-only contrast changes in final output.
Regular rendered tiles may require a tile-assembly adapter for the whole-plane
result manifest; never treat one tile as an entire section.

`align_main.py --mode tensorstore_rendering` can emit precomputed. Verify native
Z metadata and origin in its actual info file; the inspected default comments warn
about nonzero z_min. Do not assume all offsets are supported by the native writer.
For lossless output keep jpeg_compression=false.

Default tensorstore_downsample uses `downsample_z: auto` and enables JPEG; ordinary
downsample defaults to JPG. Those defaults do **not** satisfy lossless XY-only
delivery. Prefer the common exporter from accepted native results, which enforces
constant Z and raw encoding, or explicitly configure/verify the native alternative.
