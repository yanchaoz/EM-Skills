# syn178 pilot example

This directory contains rendered QC figures only. Raw EM, affinities, instance arrays, model weights, credentials, and machine-specific paths are intentionally excluded.

- Input ROI: `raw[:18, :256, :256]`
- Recorded source resolution assumption: `50 × 4 × 4 nm` (zyx)
- Model grid: `18 × 128 × 128` at `50 × 8 × 8 nm`
- Affinities: three channels
- Official SegNeuron FRMC pilot at `beta=0.25`: 35 non-background 3D instances
- Pilot approval: withheld; the volume is shallow in z, voxel metadata remains to be confirmed, and no neuron-instance ground truth was available

`segneuron-summary.*` uses the previously tested official FRMC result. `beta-sweep.*` uses the documented local fallback postprocessor to demonstrate beta comparison and selection because the Windows test environment lacked the official ELF/Vigra runtime. It is not an official FRMC benchmark. Rerun all beta candidates with the same official adapter in the target environment before selecting a production parameter.
