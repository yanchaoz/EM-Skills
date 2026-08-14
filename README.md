# EM-Skills

[中文](#中文) · [English](#english)

面向电子显微镜（EM / volume EM）的可复用 Agent Skills。当前提供 `segneuron-inference`：从体素元数据审计、分辨率调整、SegNeuron affinity 推理，到多 β 实例后处理、专业可视化、标签恢复和质量门控。

## 中文

### 当前 Skill

| Skill | 适用任务 | 入口 |
| --- | --- | --- |
| `segneuron-inference` | FIB-SEM、SBF-SEM、ATUM-SEM、ssTEM 等体电镜数据的 SegNeuron 神经元实例分割 | [`skills/segneuron-inference/SKILL.md`](skills/segneuron-inference/SKILL.md) |

### 安装到 Codex

在 Codex 中输入：

```text
请从 GitHub 仓库 yanchaoz/EM-Skills 安装 skills/segneuron-inference
```

或手动安装：

```powershell
git clone https://github.com/yanchaoz/EM-Skills.git
Copy-Item -Recurse -Force `
  .\EM-Skills\skills\segneuron-inference `
  "$env:USERPROFILE\.codex\skills\segneuron-inference"
```

重启 Codex 或新建任务以重新发现 skill。请复制完整目录，而不是只复制 `SKILL.md`。

### 在 Codex 中调用

```text
请使用 segneuron-inference skill 审计这份 zyx 体电镜数据，按物理分辨率规划模型网格，
运行 SegNeuron pilot；对 beta=[0.10, 0.25, 0.50, 0.75] 生成实例候选和对比图，
让我选择 beta 后再生成正式 instance，并输出原图、亲和图、膜和 instance overlay。
```

### 标准工作流

```text
source raw → audit → model-grid plan → pilot → affinity inference
           → beta sweep → user selects beta → final instance
           → label restoration → verify → finalize
```

```powershell
cd EM-Skills\skills\segneuron-inference
python scripts\segneuron_pipeline.py scaffold project.yaml
python scripts\segneuron_pipeline.py audit project.yaml
python scripts\segneuron_pipeline.py plan project.yaml
python scripts\segneuron_pipeline.py pilot project.yaml
python scripts\segneuron_pipeline.py infer project.yaml --execute
python scripts\segneuron_pipeline.py beta-sweep project.yaml       # 先审阅 dry-run jobs
python scripts\segneuron_pipeline.py beta-sweep project.yaml --execute
python scripts\segneuron_pipeline.py select-beta project.yaml --beta 0.25
python scripts\segneuron_pipeline.py instance project.yaml --execute
python scripts\segneuron_pipeline.py restore project.yaml --execute
python scripts\segneuron_pipeline.py verify project.yaml
python scripts\segneuron_pipeline.py finalize project.yaml
```

`infer`、`beta-sweep`、`instance` 和 `restore` 默认只生成作业规格；必须显式添加 `--execute` 才会调用外部代码。配置更改后，旧的 β 选择会失效，必须重新比较和选择。

### 配置多个 β，并让使用者选择

```yaml
instance:
  method: frmc
  scope: whole-volume
  label_dtype: uint64
  background_id: 0
  beta_sweep:
    values: [0.10, 0.25, 0.50, 0.75]

commands:
  beta_sweep:
    argv:
      - python
      - adapters/run_frmc.py
      - --affinities
      - "{output_root}/affinities"
      - --beta
      - "{beta}"
      - --output
      - "{output_root}/beta-candidates/instances-beta-{beta_tag}.npy"
    cwd: "{repo_path}"
    env: {}
    expected_outputs:
      - "beta-candidates/instances-beta-{beta_tag}.npy"
  instance:
    argv:
      - python
      - adapters/run_frmc.py
      - --beta
      - "{selected_beta}"
      - --output
      - "{output_root}/instances-model-grid"
    cwd: "{repo_path}"
    env: {}
    expected_outputs:
      - instances-model-grid
```

`beta-sweep` 为每个 β 写出独立 candidate；`select-beta` 只接受配置中存在且输出完整的 candidate。Skill 不会根据 instance 数量自动挑 β。应在相同物理切片上审查 merge、split、fragment、z 向连续性及前景泄漏。

### 专业可视化

四联图包含原始 EM、三通道 affinity、膜证据和 instance overlay：

```powershell
python scripts\segneuron_visualize.py summary `
  --raw derived\raw-model-grid.tif `
  --affinities derived\affinities.npy `
  --membrane derived\boundaries.tif `
  --membrane-mode interior `
  --instances derived\instances-model-grid.npy `
  --axis xy --index 9 `
  --resolution-nm-zyx 50 8 8 `
  --output-stem derived\qc\segneuron-summary
```

β 对比图：

```powershell
python scripts\segneuron_visualize.py beta-sweep `
  --raw derived\raw-model-grid.tif `
  --instance 0.10=derived\beta-candidates\instances-beta-0p1.npy `
  --instance 0.25=derived\beta-candidates\instances-beta-0p25.npy `
  --instance 0.50=derived\beta-candidates\instances-beta-0p5.npy `
  --instance 0.75=derived\beta-candidates\instances-beta-0p75.npy `
  --selected-beta 0.25 `
  --axis xy --index 9 `
  --resolution-nm-zyx 50 8 8 `
  --output-stem derived\qc\beta-sweep
```

默认同时输出 300 dpi PNG、可编辑文字的 SVG 和 PDF。图中颜色由 label ID 确定，所有候选保持一致；比例尺和正交切面的物理纵横比由 `resolution-nm-zyx` 标定。

### syn178 真实 pilot 示例

测试输入为 `syn178/raw[:18, :256, :256]`。在记录的元数据假设下，source grid 为 `50 × 4 × 4 nm`，模型 grid 为 `50 × 8 × 8 nm`，得到 `3 × 18 × 128 × 128` affinity。官方 SegNeuron FRMC 在 `β=0.25` 时得到 35 个三维非背景 instance；下图显示第 9 个 XY 切片，因此图中 `n_slice=10` 不等于全体积 instance 数量。

![syn178 SegNeuron summary](examples/syn178-pilot/segneuron-summary.png)

下图展示相同 affinity 在多个 β 下的实例粒度变化。由于本地 Windows 环境缺少官方 ELF/Vigra 二进制运行时，这张 β 教程图使用仓库测试时记录的 fallback 后处理器生成，仅用于展示比较与人工选择界面；正式任务应在目标 GPU 环境用同一个官方 FRMC adapter 重跑全部 β。高亮的 `β=0.25` 对应此前 pilot 设置，不代表通用推荐值。

![syn178 beta sweep](examples/syn178-pilot/beta-sweep.png)

该 pilot 的机器完整性检查通过，但质量审批仍为 **未通过 / withheld**：体积只有 18 个 z 切片、z 各向异性明显、物理分辨率来自待确认元数据，且没有神经元 instance ground truth。以上示例证明工作流、产物契约和可视化能够运行，不证明分割准确率或达到生产级重建质量。

### 远程 GPU、输出与隐私

模型代码、checkpoint、数据和环境保留在目标主机；配置中只记录固定 commit、checkpoint SHA-256 和非秘密运行参数。不要把 SSH 密码、私钥或 token 写入 YAML、命令、日志或仓库。

所有派生产物写入独立 `output.root`。该仓库不会提交模型权重、原始/派生 EM volume、服务器凭据或运行环境。完整配置字段见 [`config-schema.md`](skills/segneuron-inference/references/config-schema.md)，远程部署见 [`deployment.md`](skills/segneuron-inference/references/deployment.md)。

### 测试

```powershell
python -m unittest discover -s skills\segneuron-inference\tests -v
```

---

## English

### What is included

`segneuron-inference` is a reproducible workflow for SegNeuron-based 3D neuron instance segmentation of volume EM. It covers metadata auditing, physical-grid planning, affinity inference, beta-controlled instance postprocessing, professional visualization, label restoration, and fail-closed quality gates.

### Install and invoke

Ask Codex:

```text
Install skills/segneuron-inference from the GitHub repository yanchaoz/EM-Skills.
```

Then invoke it in natural language:

```text
Use the segneuron-inference skill on this zyx volume EM dataset. Audit its physical metadata,
plan the model grid, run a pilot, generate candidates for beta=[0.10, 0.25, 0.50, 0.75],
show me professional comparison overlays, wait for my beta choice, and only then create the final instances.
```

### Workflow and beta gate

Run `audit → plan → pilot → infer → beta-sweep → select-beta → instance → restore → verify → finalize`. The external `commands.beta_sweep` adapter receives `{beta}` and `{beta_tag}`. After candidate review, `select-beta` records the user's decision together with the configuration digest; the final adapter receives `{selected_beta}` and `{selected_beta_tag}`. A configuration change invalidates the old selection.

The runner does not infer a preferred beta from object counts. Compare identical physical slices for merges, splits, fragments, z continuity, and foreground leakage. Dry-run job specifications are written unless `--execute` is supplied.

### Visualization

`scripts/segneuron_visualize.py summary` creates a calibrated four-panel plate containing raw EM, z/y/x affinities, membrane evidence, and a deterministic instance overlay. `beta-sweep` accepts repeated `--instance BETA=PATH` arguments and highlights an optional recorded selection. It supports XY/XZ/YZ views and exports PNG, SVG, and PDF by default.

### syn178 pilot evidence

The real pilot used `syn178/raw[:18, :256, :256]`, mapped from an assumed `50 × 4 × 4 nm` source grid to a `50 × 8 × 8 nm` model grid. It produced three affinity channels at `18 × 128 × 128`. Official SegNeuron FRMC at `β=0.25` produced 35 non-background 3D instances; the summary figure above shows 10 labels intersecting one XY slice.

The beta tutorial figure uses the documented fallback postprocessor because the local Windows environment lacked the official ELF/Vigra runtime. It demonstrates the comparison and selection mechanism, not an official FRMC benchmark. The recorded pilot passed machine-integrity checks but was not approved for scientific delivery because the z extent was shallow, voxel metadata remained an assumption, cross-z continuity was limited, and no neuron-instance ground truth was available.

### Safety and reproducibility

Keep the SegNeuron checkout, weights, data, credentials, and runtime outside this repository. Pin the repository commit and checkpoint SHA-256, keep the source read-only, write outputs to a separate root, use continuous interpolation only for raw/affinity data, and use nearest-neighbor restoration for label IDs.

See the [skill instructions](skills/segneuron-inference/SKILL.md), [configuration schema](skills/segneuron-inference/references/config-schema.md), and [deployment contract](skills/segneuron-inference/references/deployment.md) for the full specification.
