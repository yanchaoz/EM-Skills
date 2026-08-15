# EM-Skills

**面向电子显微镜（EM / Volume EM）的可复用 Agent Skills**

[English](README.md) | 简体中文

EM-Skills 是面向专业电子显微镜数据分析的可复用 Agent Skills 集合。每个 Skill 组合了领域知识、任务路由、确定性脚本、按需参考资料和科研质量门禁。

Skill 不是一条必须从头跑到尾的固定工作流。它既可以只审计一份数据、绘制已有结果、比较后处理候选或运行 Pilot，也可以协调完整分析。Agent 应选择满足请求所需的最小能力集合，并优先复用已有产物。

目标很简单：

> 将专业 EM 方法封装成 AI Agent 可以选择、执行、检查和验证的可复用能力。

---

## 当前 Skills

| Skill                                                        | 功能                                 |
| ------------------------------------------------------------ | ---------------------------------- |
| [`segneuron-inference`](skills/segneuron-inference/SKILL.md) | 基于 SegNeuron 的 Volume EM 三维神经元实例分割 |
| [`mitonet-inference`](skills/mitonet-inference/SKILL.md) | 基于 MitoNet/Empanada 的线粒体语义与三维实例分割 |
| [`suggest-em-annotations`](skills/suggest-em-annotations/SKILL.md) | 基于 EMFoundation embedding 的可变尺寸子体块选择与人工标注建议 |

### Skill 设计

每个 Skill 都遵循同一套运行方式：

* frontmatter 中的 `description` 决定何时触发 Skill；
* `SKILL.md` 把请求路由到最小必要能力；
* `scripts/` 提供可复现操作，避免 Agent 临时重写命令或算法；
* `references/` 只在任务需要相应模型、配置、部署或 QC 细节时加载；
* 科研审批门禁用于限制结论和最终交付，不会迫使一次简单审计或绘图执行完整流水线。

`segneuron-inference` 适用于：

* FIB-SEM
* SBF-SEM
* ATUM-SEM
* ssTEM
* 其他连续切片或 Volume EM 数据

---

## 安装

在 Codex 中直接输入：

```text
请从 GitHub 仓库 yanchaoz/EM-Skills 安装 skills/segneuron-inference。
请从 GitHub 仓库 yanchaoz/EM-Skills 安装 skills/mitonet-inference。
请从 GitHub 仓库 yanchaoz/EM-Skills 安装 skills/suggest-em-annotations。
```

请安装完整的 Skill 目录，而不是只复制 `SKILL.md`。

安装完成后，新建 Codex 任务即可重新发现并使用该 Skill。

---

## 如何使用

直接用自然语言指定一个能力或完整目标即可。例如，下面这些都是有效请求：

```text
使用 $segneuron-inference 审计这份数据的轴顺序和物理网格，不要运行推理。
使用 $segneuron-inference 比较这些已有 beta 候选并绘制 overlay。
使用 $mitonet-inference 对照原始 EM 检查这份已有的线粒体 instance volume。
使用 $suggest-em-annotations 对已有选择绘制 UMAP，不要重新提取 embedding。
```

对于端到端目标，Skill 才会展开达到结果所需的完整阶段。

例如：

```text
请使用 segneuron-inference skill 对这份 zyx Volume EM 数据进行神经元实例分割。

首先检查数据尺寸、轴顺序和物理 voxel resolution，
并根据真实物理分辨率规划 SegNeuron 的模型输入尺度。

先选择一个具有代表性的区域运行 pilot，
确认模型输出和分割效果没有明显问题。

随后进行 affinity inference，并生成
beta = [0.10, 0.25, 0.50, 0.75]
对应的多个实例分割候选。

请在相同物理位置生成对比图，
让我检查 merge、split、fragment、foreground leakage 和 z 向连续性。

等我选择 beta 后，再生成最终三维 instance segmentation。

最后恢复到目标分辨率，
检查输出完整性，并生成完整的质量控制可视化。
```

也可以更简洁地调用：

```text
使用 segneuron-inference 处理这个 Volume EM 数据。

先运行 pilot，再比较多个 beta，
等我确认后生成最终三维神经元实例分割。
```

### MitoNet 调用示例

```text
请使用 mitonet-inference skill 处理这份 zyx Volume EM 数据。
先审计轴顺序和真实 voxel resolution，再运行代表性 Pilot。
比较不同 xy 尺度、阈值和后处理参数对应的 MitoNet profiles。
生成原始 EM、线粒体前景、instance overlay 和 XZ 连续性图。
等我选择 profile 后，再进行全体积推理和标签恢复。
```

MitoNet 工作流会分别检查 semantic foreground、逐切片 panoptic instance、三维 stack matching、source-grid 恢复和科研审批。


### EM 标注建议调用示例

```text
请使用 suggest-em-annotations skill，在固定标注体素预算下，从这份 zyx Volume EM 数据中规划可变尺寸的神经元分割标注区域。
先审计 voxel size、轴顺序、数据源身份和 holdout 范围；使用固定版本 EMFoundation BASE 编码器生成真实的 512 维 embedding，
执行多尺度、预算约束的 coverage-guided 子体块选择，并绘制空间位置、embedding 覆盖、原始 EM gallery、覆盖率曲线和人工审核队列。
等待我逐个 accept/reject 后，再导出最终标注清单。
```

该工作流将 SL-SSNS 的 constrained coverage rate 思路扩展为可审计的多尺度、成本感知标注建议流程。它不会自动生成标签，会强制排除配置中的验证/测试区域，记录数据、模型和配置哈希，并在最终导出前要求具名人工审核。

---

## 参考端到端流程

当没有可复用产物、并且目标是完成一份新的 SegNeuron 分割时，参考流程为：

```text
原始 Volume EM
        ↓
数据与元数据审计
        ↓
物理分辨率规划
        ↓
代表性区域 Pilot
        ↓
SegNeuron Affinity 推理
        ↓
多 Beta 实例候选
        ↓
可视化比较
        ↓
人工选择 Beta
        ↓
最终三维实例分割
        ↓
标签恢复
        ↓
验证与质量控制
        ↓
最终结果
```

### 1. 数据审计

Skill 首先检查与任务相关的基础信息，包括：

* volume 尺寸；
* 轴顺序；
* voxel resolution；
* 物理单位；
* 图像基本特征；
* 数据与模型输入尺度是否兼容。

物理元数据不是可有可无的工程细节，而是 Volume EM 分析的一部分。

---

### 2. 物理分辨率规划

不同 Volume EM 数据的 voxel size 往往存在明显差异，尤其是 z 方向经常具有较强各向异性。

因此，Skill 根据**真实物理分辨率**规划模型输入尺度，而不是简单根据数组大小缩放。

这样能够避免不同成像平台、不同制样方式和不同采样分辨率对模型尺度造成混淆。

---

### 3. 先 Pilot，再全量处理

正式处理整个 volume 之前，首先选择一个具有代表性的局部区域运行 Pilot。

Pilot 主要用于验证：

* 数据方向是否正确；
* 分辨率处理是否合理；
* 模型是否兼容；
* affinity 输出是否正常；
* instance reconstruction 是否合理；
* 可视化是否正确；
* 后处理流程是否可以运行。

只有 Pilot 没有明显问题后，才建议继续处理更大的数据。

---

### 4. Affinity 推理

SegNeuron 首先预测描述局部神经结构连接关系的 affinity。

Affinity prediction 随后作为三维实例重建的基础。

Skill 将：

```text
Affinity Prediction
```

和：

```text
Instance Reconstruction
```

明确拆分为两个阶段，从而更容易判断问题究竟来源于模型预测还是后处理。

---

### 5. 多 Beta 比较

实例重建结果会受到后处理参数 `beta` 的明显影响。

因此，Skill 不默认把某一个 beta 直接作为最终答案，而是可以一次生成多个候选，例如：

```text
beta = 0.10
beta = 0.25
beta = 0.50
beta = 0.75
```

并在相同物理位置进行比较。

重点检查：

* 神经突起是否被错误 merge；
* 同一神经结构是否被过度 split；
* 是否存在大量 fragment；
* 是否向非神经区域发生 foreground leakage；
* z 方向是否具有连续性；
* 弱膜区域是否产生错误连接；
* 三维拓扑是否合理。

Skill **不会单纯根据 instance 数量自动选择 beta**。

因为 instance 数量更多或更少，都不能直接代表重建结果更好。

---

### 6. 人工选择

不同 beta 的候选结果生成后，由使用者进行比较并明确选择最终参数。

这个步骤形成一个显式的 **human-in-the-loop gate**。

也就是说：

```text
模型生成候选
      ↓
Agent 整理和可视化
      ↓
研究者判断
      ↓
最终重建
```

如果数据处理方式、模型配置或其他关键设置发生变化，之前选择的 beta 不应被默认继续沿用。

---

### 7. 最终三维重建

用户完成 beta 选择后，Skill 才会生成正式的三维 neuron instance segmentation。

如果模型推理尺度与原始数据尺度不同，最终 instance label 还可以恢复到目标坐标系和目标分辨率，同时保持离散 label ID 的完整性。

---

### 8. 验证与质量控制

任务成功运行并不代表结果自动具有科研可信度。

Skill 会进一步检查输出是否完整、配置是否一致，以及当前证据是否足以支持后续科学分析。

因此，一个任务可能出现：

```text
运行完成
+
输出完整
+
技术流程正确
```

但仍然：

```text
Scientific approval withheld
```

这种设计是有意的。

---

## 效果展示

Skill 提供标准化的科研可视化，用于检查完整的 SegNeuron 分割流程。

典型结果包括：

1. 原始 EM；
2. SegNeuron affinity prediction；
3. membrane / boundary evidence；
4. neuron instance overlay。

示例：

![syn178 SegNeuron summary](examples/syn178-pilot/segneuron-summary.png)

Instance 使用稳定的 label-based 配色，因此同一个实例在不同切片和不同可视化结果中能够保持一致颜色。

同时，物理 voxel resolution 可以用于标定比例尺以及正交切面的真实物理纵横比。

---

## Beta 对比

同一组 affinity 可以使用不同 beta 进行实例重建，并生成并排比较结果。

示例：

![syn178 beta sweep](examples/syn178-pilot/beta-sweep.png)

这样可以直观看到随着 beta 改变：

* segmentation granularity 如何变化；
* merge 是否增加；
* split 是否增加；
* fragment 是否明显；
* 神经结构的三维连接是否改变。

最终 beta 应根据分割质量决定，而不是根据 instance 数量决定。

---

## syn178 Pilot 示例

仓库中包含一个小规模真实 Pilot 示例：

```text
syn178/raw[:18, :256, :256]
```

在记录的元数据假设下：

```text
source grid: 50 × 4 × 4 nm
model grid:  50 × 8 × 8 nm
```

Pilot 生成了三通道 SegNeuron affinity，并进一步得到了对应的三维 neuron-instance candidates。

在此前记录的：

```text
beta = 0.25
```

配置下，官方 SegNeuron FRMC 后处理器得到：

```text
35
```

个非背景三维实例。

该示例说明整个工作流能够完成端到端运行。

但它**不代表已经达到生产级或科研级分割准确率**。

---

## 为什么该 Pilot 没有被视为科学验证

syn178 示例的主要目的是验证工作流，而不是作为 SegNeuron 的正式 benchmark。

当前没有给予 scientific approval，原因包括：

* volume 只有 18 个 z 切片；
* z 向各向异性明显；
* 物理分辨率来自仍需进一步确认的元数据；
* z 方向范围较小，不足以充分评价长距离神经结构连续性；
* 没有 neuron-instance ground truth。

因此：

> 一个工作流能够成功运行，并不等价于分割结果已经得到科学验证。

---

## MitoNet syn178 Pilot

仓库包含基于 `syn178/raw[:18, :256, :256]` 的远程 MitoNet-mini 工作流示例。8 nm 与 16 nm 两个 profile 检测到同一个线粒体候选，二值掩膜 Dice 为 `0.8710`；8 nm 结果保留了稍大的边界和额外一个 z 切片。

![syn178 MitoNet 8 nm QC](examples/syn178-mitonet-pilot/qc-scale-8nm.png)

![syn178 MitoNet 16 nm QC](examples/syn178-mitonet-pilot/qc-scale-16nm.png)

参数、哈希、局限性和矢量图见 [MitoNet Pilot 记录](examples/syn178-mitonet-pilot/README.md)。该示例用于证明执行与 QC 链路，不是 ground-truth benchmark。

---

## AC3AC4 真实标注建议 Pilot

标注建议 Skill 已在远端使用 `Pretraining_mito/models/BASE/learner.ckpt`，对真实的 `Figure2-Exps/data/AC3AC4/0.tif` 完成端到端运行。

- 输入：`256 × 1024 × 1024`、`uint8`、zyx；
- 编码器：74/74 个兼容权重完整加载，输出 512 维 PNIv2 pooled feature；
- embedding：`3375 × 512`；
- 候选：4 种尺寸，共 8,410 个子体块；
- 预算：24,000,000 个原始体素，最多 6 个框；
- 选择结果：6 个框，共使用 22,806,528 个体素；
- embedding coverage：`k=30` 时为 49.63%。

![AC3AC4 标注建议总览](examples/ac3ac4-annotation-advisor/selection-overview.png)

![AC3AC4 原始 EM 审核 gallery](examples/ac3ac4-annotation-advisor/raw-subvolume-gallery.png)

精确哈希、坐标、配置和限制见 [完整 Pilot 记录](examples/ac3ac4-annotation-advisor/README.md)。当前队列仍是需要人工逐项审核的 draft；较高 embedding coverage 不能单独证明下游分割性能提升。

---

## 设计原则

EM-Skills 遵循几个基本原则。

### 物理尺度优先

Volume EM 分析不能只看数组大小。

不同 voxel size 对应完全不同的真实生物学尺度，因此模型部署应基于物理分辨率进行规划。

---

### 先 Pilot，再大规模运行

大型 EM 数据通常具有很高的计算和存储成本。

应该首先用代表性区域验证完整流程，再进行全量处理。

---

### 模型预测与实例重建分开

Affinity inference 和 neuron instance reconstruction 是不同阶段，也具有不同的失败模式。

应该分别检查。

---

### 拓扑敏感参数保留人工判断

对于 neuron reconstruction 这类高度依赖拓扑正确性的任务，单一统计指标通常不足以自动决定最优后处理参数。

人工检查仍然是工作流的重要组成部分。

---

### 保留可复现性

关键的数据、模型、分辨率和后处理决策都应该可以被追踪和复现。

---

### Fail Closed

当关键元数据缺失、输出不完整或者当前证据不足时，Skill 应明确报告问题，而不是默认结果已经可靠。

---

## 适用方向

EM-Skills 主要面向：

* Connectomics；
* 神经元三维重建；
* 神经元实例分割；
* 细胞器分割；
* 超微结构分析；
* 大规模 Volume EM；
* AI-assisted EM analysis；
* 科研级 EM 质量控制。

未来该仓库计划逐步扩展为更完整的 EM 专业 Agent Skills 集合。

---

## 文档

当前 Skill 的完整技术说明见：

* [SegNeuron Inference Skill](skills/segneuron-inference/SKILL.md)
* [配置说明](skills/segneuron-inference/references/config-schema.md)
* [部署说明](skills/segneuron-inference/references/deployment.md)
* [MitoNet Inference Skill](skills/mitonet-inference/SKILL.md)
* [MitoNet 配置说明](skills/mitonet-inference/references/config-schema.md)
* [EM 标注建议 Skill](skills/suggest-em-annotations/SKILL.md)、[EMFoundation 适配器](skills/suggest-em-annotations/references/emfoundation-adapter.md) 与 [评估方案](skills/suggest-em-annotations/references/evaluation-protocol.md)

---

## Repository Philosophy

EM-Skills 既不是一批相互独立的推理脚本，也不是一组僵硬的固定流水线。

它把专业 EM 能力封装成 Agent 可以理解和执行的 Skill，将：

```text
领域知识
   +
模型执行
   +
物理尺度推理
   +
人工判断
   +
质量控制
   +
可复现性
```

组合起来。Agent 会把每个请求路由到相关能力子集；只有目标确实需要时，才协调端到端流程。

---

## License

使用与再分发条款请参见仓库 License。
