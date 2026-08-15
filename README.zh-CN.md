# EM-Skills

**面向电子显微镜与 Volume EM 的可复用 Agent Skills**

[English](README.md) | 简体中文

EM-Skills 将专业 EM 方法封装为按任务路由的 Agent Skills。每个 Skill 组合了领域知识、确定性脚本、模型与配置参考资料，以及科研质量门禁。

既可以只调用一个能力，例如审计元数据、比较 beta 或绘制已有标签；也可以组合多个 Skills 完成新数据集适配。Agent 应优先复用已有产物，只执行达到目标所需的阶段。

## Skills 总览

| Skill | 适用任务 | 主要输出 |
| --- | --- | --- |
| [`segneuron-inference`](skills/segneuron-inference/SKILL.md) | SegNeuron affinity 推理与三维神经元重建 | affinity、多 beta instance、source-grid 标签、QC 图 |
| [`mitonet-inference`](skills/mitonet-inference/SKILL.md) | MitoNet/Empanada 线粒体分割 | semantic mask、三维 instance、profile 对比、QC 图 |
| [`suggest-em-annotations`](skills/suggest-em-annotations/SKILL.md) | 基于 embedding 的可变尺寸子体块选择 | 标注队列、UMAP/空间审核、获批清单 |
| [`bootstrap-em-segmentation`](skills/bootstrap-em-segmentation/SKILL.md) | 新 EM 数据上的跨 Skill 模型适配 | 粗分割、选择性修正、训练交接、配对评估 |
| [`cloudvolume-video`](skills/cloudvolume-video/SKILL.md) | Neuroglancer 数据准备、局部 overlay、密度图、平滑镜头与三维 mesh 展示 | 验证后 precomputed、viewer 交接、MP4、PLY mesh |

输入可包括 TIFF、NumPy、Zarr、N5、CloudVolume/precomputed，以及 FIB-SEM、SBF-SEM、ATUM-SEM、ssTEM 等连续切片或体电镜数据。

## Skills 如何联动

单阶段请求直接交给对应 Skill；当请求跨越粗分割、选择性修正和模型适配时，由 `$bootstrap-em-segmentation` 协调。

```text
未见过的 3D EM（xy: 5–10 nm）
  → $segneuron-inference：零样本粗分割
  → $suggest-em-annotations：可变尺寸区域选择
  → 人工专家：连通性修正
  → SegNeuron 微调或轻量模型训练
  → $segneuron-inference：配对 holdout 评估
  ↺ 仅从训练区域选择新样本并继续迭代
```

**5–10 nm xy 是适用性检查范围，不是性能保证。** 通用 checkpoint 可能在未见数据上产生较好的粗分割，但只有通过代表性 Pilot 和独立 holdout 评估后，才能声称达到突出性能。

选择性标注由 `$suggest-em-annotations` 完成：它在固定预算下选择可变尺寸区域。专家查看 raw/coarse overlay，并在获批子体块内修正连通性。只有存在真实、固定版本的训练适配器时才执行训练。

当分割产物与物理网格固定后，可调用 `$cloudvolume-video` 准备并验证派生的 Neuroglancer precomputed 图层，再展示选定局部视野或 mesh 场景；它不会修改上游标签或模型决策。

## 快速开始

### 安装

让 Codex 安装一个或多个完整 Skill 目录：

```text
请从 yanchaoz/EM-Skills 安装 skills/segneuron-inference。
请从 yanchaoz/EM-Skills 安装 skills/mitonet-inference。
请从 yanchaoz/EM-Skills 安装 skills/suggest-em-annotations。
请从 yanchaoz/EM-Skills 安装 skills/bootstrap-em-segmentation。
请从 yanchaoz/EM-Skills 安装 skills/cloudvolume-video。
```

请安装整个目录，而不是只复制 `SKILL.md`。安装后新建 Codex 任务，使 Skills 被重新发现。

### 提供必要信息

处理新数据时，请尽量提供：

- 数据路径或 URI 与格式；
- 轴顺序，例如 `zyx`；
- 以 nm 表示的真实 voxel size；
- 任务目标与输出位置；
- 执行所需 checkpoint、环境或后端；
- 必须隔离的 validation/test/holdout 范围。

关键科研元数据缺失或互相矛盾时，Skill 会报告问题，不会自行猜测。

## 调用示例

### 1. 神经元重建与 beta 审核

```text
请对这份 50 × 4 × 4 nm、zyx Volume EM 使用 $segneuron-inference。
先运行代表性 Pilot，生成 affinity，并在相同物理位置比较
beta = [0.10, 0.25, 0.50, 0.75]。展示 raw EM、affinity、membrane
和 instance overlay；等我选择 beta 后再生成最终结果。
```

如果只需要一个阶段：

```text
请用 $segneuron-inference 比较这些已有 beta 候选并绘制 overlay，
不要重新运行推理。
```

### 2. 线粒体分割

```text
请对这份 zyx EM volume 使用 $mitonet-inference。审计 voxel size，
运行 Pilot，比较命名的 8 nm 与 16 nm profiles，并绘制 raw、foreground、
instance overlay 和 XZ 连续性图。等我选择 profile 后再继续。
```

### 3. 选择性标注

```text
请用 $suggest-em-annotations 在 24,000,000 voxel 预算下，从这份数据中
选择可变尺寸的神经元标注区域。使用固定的 EMFoundation BASE encoder，
排除 holdout，绘制 UMAP、空间位置和 raw review 图；等我逐个接受或拒绝后，
再导出最终标注队列。
```

### 4. 未见数据集适配

```text
请对这份未见过的 30 × 8 × 8 nm、zyx EM 数据使用
$bootstrap-em-segmentation。先生成 SegNeuron zero-shot 粗分割，再用
$suggest-em-annotations 选择可变尺寸修正区域；为专家准备 raw/coarse overlay，
导出经过验证的训练交接，并在冻结 holdout 上比较适配后的 checkpoint。
```

### 5. Neuroglancer 准备与 CloudVolume 展示

```text
请对这些肾脏数据使用 $cloudvolume-video。如果输入是 TIFF、NPY、Zarr 或 N5，
先按明确的轴顺序和 voxel size 生成派生的 Neuroglancer precomputed 数据，
做精确回读验证并生成 viewer 交接；已有 precomputed 输入则跳过转换。然后审计物理对齐，
使用有界的 1 x 1 mm context ROI，在完全相同的坐标上依次展示分割结果和密度图。
记录随机种子，从该 context 内随机选择四个组织有效的 200 x 112.5 um 局部视野；
让镜头分别可见地移动到四个位置并停留展示组合 overlay。不要把随机位置擅自命名为
解剖区域，也不要在每个局部位置重复全部 context 阶段。让 raw 与 mask 始终共用一个物理变换。
如果存在有效的三维 mesh
元数据，导出指定 segment IDs，并生成经过验证的 turntable 视频。
```

## Skill 运行时保留什么

| 关注点 | 处理方式 |
| --- | --- |
| 物理尺度 | 记录轴、voxel size、offset、bounds 与 source/model/delivery grids |
| 可复现性 | 固定数据、代码、checkpoint、配置、命令与输出身份 |
| 昂贵计算 | 先审计、规划、Pilot 和 dry-run job，再扩大规模 |
| 人工决策 | 记录 beta/profile 选择和标注 accept/reject |
| 科研结论 | 区分完整性/QC 与准确率；性能结论必须有 holdout 证据 |
| 失败处理 | 元数据、数据泄漏、网格、模型或产物异常时停止并报告 |

完整字段、参数和命令位于各 Skill 的 `references/` 与 `scripts/` 中。

## 真实结果示例

以下示例用于展示执行和 QC 链路，不能替代 ground-truth benchmark。

### SegNeuron：`syn178/raw[:18, :256, :256]`

- 记录的 source/model grids：`50 × 4 × 4 nm → 50 × 8 × 8 nm`；
- 生成三通道 affinity；
- 在记录的 `beta = 0.25` 下得到 35 个非背景 instance；
- 仅包含 18 个 z slices，且没有神经元 instance ground truth。

| 四面板汇总 | Beta 对比 |
| --- | --- |
| ![syn178 SegNeuron summary](examples/syn178-pilot/segneuron-summary.png) | ![syn178 beta sweep](examples/syn178-pilot/beta-sweep.png) |

[SegNeuron Pilot 记录](examples/syn178-pilot/README.md)

### MitoNet：`syn178/raw[:18, :256, :256]`

8 nm 与 16 nm MitoNet-mini profiles 检测到同一个线粒体候选，二值 mask Dice 为 `0.8710`。这是没有线粒体 ground truth 的 profile/QC 对比。

| 8 nm profile | 16 nm profile |
| --- | --- |
| ![MitoNet 8 nm QC](examples/syn178-mitonet-pilot/qc-scale-8nm.png) | ![MitoNet 16 nm QC](examples/syn178-mitonet-pilot/qc-scale-16nm.png) |

[MitoNet Pilot 记录](examples/syn178-mitonet-pilot/README.md)

### 标注建议：AC3/AC4 `0.tif`

- 输入：`256 × 1024 × 1024`、`uint8`、zyx；
- embedding：EMFoundation BASE encoder 生成的 `3375 × 512` 特征；
- candidates：四种尺寸共 8,410 个候选框；
- 选择：六个框，使用 22,806,528 / 24,000,000 预算 voxel；
- embedding coverage：49.63%，`k = 30`。

| 选择结果 | Raw 子体块审核 |
| --- | --- |
| ![AC3AC4 annotation selection](examples/ac3ac4-annotation-advisor/selection-overview.png) | ![AC3AC4 raw review gallery](examples/ac3ac4-annotation-advisor/raw-subvolume-gallery.png) |

该队列仍是需要人工审核的 draft；embedding coverage 本身不能证明下游分割得到提升。[完整标注建议记录](examples/ac3ac4-annotation-advisor/README.md)

### CloudVolume 视频：肾脏局部视野

视频在一个有界的 **1 x 1 mm** context ROI 上展示分割结果与密度图，随后可见地移动到该 ROI 内四个由固定种子生成的 **200 x 112.5 um** 随机局部视野，并停留展示组合 overlay。随机位置使用中性编号，不推断解剖身份。密度表示预测结构在有效组织像素中的占比，不能替代 ground-truth 准确率评估。

| 视频关键帧验证 | 固定种子的随机局部占比汇总 |
| --- | --- |
| ![肾脏视频 mask、overlay 与密度关键帧](examples/kidney-local-cloudvolume-video/kidney-local-fields-tour-contact-sheet.jpg) | ![肾脏局部密度对比](examples/kidney-local-cloudvolume-video/local-region-density-comparison.png) |

[▶ 查看或下载经过验证的 30.5 秒、1080p 肾脏 context-to-random-local 视频](examples/kidney-local-cloudvolume-video/kidney-local-fields-tour.mp4)

该肾脏来源是单切片 WSI，因此不会被包装成真实三维 mesh 结果。Skill 测试会独立验证已有 mesh 读取、有界标签转 mesh、完整 PLY 导出、无界面 turntable 渲染与视频校验。[完整局部视野记录](examples/kidney-local-cloudvolume-video/README.md)

## 科研质量门禁

- 根据真实 voxel size 选择模型网格，不只依据数组尺寸。
- 全体积昂贵计算前先运行代表性 Pilot。
- 将预测、后处理、标签恢复和科研审批分别检查。
- 不把 affinity、semantic mask 或建议框称为最终 instance label。
- selection 与 training 必须排除 validation/test/holdout。
- 对拓扑敏感参数和专家修正保留人工决策记录。
- 区分“运行成功”“QC 合理”和“准确率得到验证”。

## 仓库结构

```text
EM-Skills/
├── skills/
│   ├── segneuron-inference/
│   ├── mitonet-inference/
│   ├── suggest-em-annotations/
│   ├── bootstrap-em-segmentation/
│   └── cloudvolume-video/
├── examples/
├── README.md
└── README.zh-CN.md
```

每个 Skill 都包含凝练的 `SKILL.md`、`agents/` 中的界面元数据，以及按需提供的 `scripts/`、`references/` 和 `evals/`。

## 技术文档

- SegNeuron：[Skill](skills/segneuron-inference/SKILL.md) · [配置](skills/segneuron-inference/references/config-schema.md) · [分辨率与网格](skills/segneuron-inference/references/resolution-and-grids.md) · [部署](skills/segneuron-inference/references/deployment.md)
- MitoNet：[Skill](skills/mitonet-inference/SKILL.md) · [模型契约](skills/mitonet-inference/references/model-contract.md) · [配置](skills/mitonet-inference/references/config-schema.md)
- 标注建议：[Skill](skills/suggest-em-annotations/SKILL.md) · [EMFoundation 适配器](skills/suggest-em-annotations/references/emfoundation-adapter.md) · [评估方案](skills/suggest-em-annotations/references/evaluation-protocol.md)
- 自适应重建：[Skill](skills/bootstrap-em-segmentation/SKILL.md) · [跨 Skill 组合契约](skills/bootstrap-em-segmentation/references/composition-contract.md)
- CloudVolume 视频：[Skill](skills/cloudvolume-video/SKILL.md) · [配置](skills/cloudvolume-video/references/config-schema.md) · [precomputed 契约](skills/cloudvolume-video/references/precomputed-contract.md) · [mesh 契约](skills/cloudvolume-video/references/mesh-contract.md) · [质量门禁](skills/cloudvolume-video/references/quality-gates.md)

## License

使用与再分发条款请参见仓库 License。
