# EM-Skills

面向电子显微镜（EM / volume EM）数据分析的可复用 Agent Skills。当前首个 skill 是 **SegNeuron Inference**：用于审计、规划、部署和验证基于 SegNeuron 的三维神经元实例分割流程。

## Skills

| Skill | 适用任务 | 入口 |
| --- | --- | --- |
| `segneuron-inference` | FIB-SEM、SBF-SEM、ATUM-SEM、ssTEM 等体电镜数据的分辨率适配、SegNeuron affinity 推理、FRMC 实例化、标签恢复和质量控制 | [`skills/segneuron-inference/SKILL.md`](skills/segneuron-inference/SKILL.md) |

## 安装到 Codex

在 Codex 中直接输入：

```text
请从 GitHub 仓库 yanchaoz/EM-Skills 安装 skills/segneuron-inference
```

也可以手动安装。先克隆仓库，再把整个 skill 目录复制到 Codex skills 目录：

```powershell
git clone https://github.com/yanchaoz/EM-Skills.git
Copy-Item -Recurse -Force `
  .\EM-Skills\skills\segneuron-inference `
  "$env:USERPROFILE\.codex\skills\segneuron-inference"
```

重启 Codex 或新建一个任务，使其重新发现 skill。请保留完整目录结构；不要只复制 `SKILL.md`，因为工作流还依赖 `scripts/`、`references/` 和 `assets/`。

## 不安装，直接使用

下载或克隆仓库后，可以从 skill 目录直接运行编排器：

```powershell
cd EM-Skills\skills\segneuron-inference
python scripts\segneuron_pipeline.py scaffold project.yaml
python scripts\segneuron_pipeline.py audit project.yaml
python scripts\segneuron_pipeline.py plan project.yaml
```

`scaffold` 会创建项目配置。若使用 YAML 配置，需要安装 PyYAML；也可以从 `assets/project.example.json` 开始，以避免该依赖。

```powershell
python -m pip install PyYAML
```

## 在 Codex 中调用

安装后不需要记住 skill 名称；描述任务即可触发。例如：

```text
请用 SegNeuron 对这个 volume EM 数据做神经元实例分割。
源数据是 D:\data\raw.npy，轴顺序 zyx，分辨率为 40×8×8 nm。
先 audit 和 plan，只生成 dry-run 作业，不要立即执行模型。
```

明确调用也可以：

```text
请使用 segneuron-inference skill，审计数据元信息，规划模型网格，
在代表性 ROI 上运行 pilot，通过后再生成 affinity 和 neuron instances，
最后把标签恢复到源网格并完成 verify。
```

## 标准工作流

```text
source raw
  -> audit
  -> model-grid planning / resampling
  -> pilot ROI
  -> SegNeuron affinity inference
  -> FRMC neuron instances
  -> optional block reconciliation
  -> nearest-neighbor label restoration
  -> verification and delivery manifest
```

推荐按以下顺序运行：

```powershell
python scripts\segneuron_pipeline.py scaffold project.yaml
python scripts\segneuron_pipeline.py audit project.yaml
python scripts\segneuron_pipeline.py plan project.yaml
python scripts\segneuron_pipeline.py pilot project.yaml
python scripts\segneuron_pipeline.py infer project.yaml
python scripts\segneuron_pipeline.py infer project.yaml --execute
python scripts\segneuron_pipeline.py instance project.yaml --execute
python scripts\segneuron_pipeline.py restore project.yaml --execute
python scripts\segneuron_pipeline.py verify project.yaml
python scripts\segneuron_pipeline.py finalize project.yaml
```

其中 `infer`、`instance` 和 `restore` 默认是 dry-run：只生成经过渲染的作业规格，不会调用第三方代码；显式加入 `--execute` 后才会执行。

## 配置 SegNeuron

从 [`assets/project.example.yaml`](skills/segneuron-inference/assets/project.example.yaml) 或 JSON 示例复制一份项目配置，并至少填写：

- 源数据 URI、格式、`zyx` shape、物理分辨率、offset 和 bbox；
- 固定的 SegNeuron 仓库 commit；
- 模型 checkpoint 路径及 SHA-256；
- 模型目标分辨率、patch、halo 和 normalization 策略；
- pilot ROI；
- `infer`、`instance`、`restore` 的参数列表命令和工作目录；
- 独立于源数据的输出目录。

命令必须写成参数列表，而不是 shell 字符串。例如：

```yaml
commands:
  infer:
    argv:
      - python
      - inference.py
      - --config
      - "{config_path}"
    cwd: "{repo_path}"
    env: {}
    expected_outputs:
      - affinities
```

完整字段说明见 [`references/config-schema.md`](skills/segneuron-inference/references/config-schema.md)。SegNeuron 研究代码适配约定见 [`references/segneuron-adapter.md`](skills/segneuron-inference/references/segneuron-adapter.md)。

## 远程 GPU / Connect / SSH

Skill 不保存服务器密码、SSH 私钥或 token。推荐流程是：

1. 在本地完成 `audit` 和 `plan`；
2. 将数据、SegNeuron 代码、checkpoint 和配置放到远程 GPU 主机；
3. 固定代码 commit、checkpoint SHA-256、Python/CUDA 环境和工作目录；
4. 先生成并审核 dry-run 作业；
5. 通过 Connect、SSH 或调度器执行，并把日志与产物写到 `output.root`；
6. 拉回 QC 图和 manifest，完成 `verify`/`finalize`。

远程适配、可恢复执行和日志要求见 [`references/deployment.md`](skills/segneuron-inference/references/deployment.md)。凭据应通过环境或安全凭据管理器提供，不能写入项目 YAML、命令参数、日志或仓库。

## 输出在哪里

所有派生产物都位于配置中的 `output.root`，典型内容包括：

```text
output.root/
  audit/
  plan/
  jobs/
  logs/
  affinities/
  instances-model-grid/
  instances-source-grid/
  qc/contact-sheet.png
  verification/
  delivery-manifest.json
```

实际目录名由项目配置决定。源数据必须保持只读，`output.root` 不能与源路径重叠。

## 关键设计约束

- SegNeuron 输出首先是 affinity，不是最终实例标签；
- raw/affinity 可用连续插值，instance label 只能使用最近邻恢复；
- z 分辨率默认保持不变，除非固定的模型 profile 和 pilot 证据支持调整；
- per-block instances 在完成全局 ID 对齐前不能视为最终结果；
- pilot 未通过时不得进入全量运行；
- 权重、数据、运行环境和凭据均在仓库外管理。

## 测试

```powershell
python -m unittest discover -s skills\segneuron-inference\tests -v
```

测试覆盖配置审计、物理网格规划、dry-run/execute 边界、标签安全检查和最终交付门控。

## 仓库内容与隐私

本仓库只包含 skill 指令、编排脚本、配置模板、参考文档和测试。不会提交：

- SegNeuron 模型权重；
- 原始或派生 EM 数据；
- SSH 密码、私钥、token 或服务器配置；
- 本地/远程运行日志和实验输出。

