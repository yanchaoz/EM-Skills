# Select a backend

These routes are alternatives. Do not successively warp the same stack with all three.

| Route | Appropriate pilot | Required resources / common failure |
|---|---|---|
| SOFIMA | Textured serial sections with optical-flow correspondences; mesh regularization | JAX environment; GPU useful. Large rigid offsets, poor texture and invalid boundary flow require explicit handling. |
| metroEM + corgie | A compatible learned SEAMLeSS model and blockwise, multi-reference large-volume alignment | PyTorch/modelhouse environment, model files and physical-scale evidence. A model for a different acquisition is not automatically transferable. |
| FEABAS | Tile/section assembly with explicit geometry, masks and finite-element constraints | Native dependencies, RAM/CPU workers and correct loaders. Broken pieces need component/material handling; wrong mask polarity can exclude the specimen. |

Use the user's requested algorithm when feasible. If its model or environment is
missing, audit/plan and identify the missing requirement; do not silently substitute
another method. For comparisons, align the same physical pilot and use a common
reference and common evaluation support. A visually smoother stack can have worse
biological deformation. No universal winner is claimed.

[upstreams.json](upstreams.json) records inspected revisions and licenses. Pin
checkouts, capture Python/package/GPU versions and command/config hashes in each
actual run. The pins document this recipe's source audit, not guaranteed dependency
compatibility on every host. Separate virtual environments avoid conflicts among
JAX, the older corgie stack and current FEABAS dependencies. Do not vendor upstream
code or checkpoints into this skill.
