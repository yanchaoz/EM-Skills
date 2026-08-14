# syn178 MitoNet pilot / syn178 MitoNet 小规模测试

English | 中文

This example demonstrates the `mitonet-inference` skill on the same bounded Volume EM crop used by the SegNeuron pilot:

```text
syn178/raw[:18, :256, :256]
```

The crop was prepared on a `50 × 8 × 8 nm` model grid with shape `18 × 128 × 128` (`zyx`). The remote test used the official quantized MitoNet-mini artifact and Empanada v0.1.7 commit `01c6e7aa3ad0e3c3334df8b129b0122724b6ad2e` in stack mode.

Two resolution profiles were compared:

| Profile | Downsample factor | Objects | Foreground | z span |
|---|---:|---:|---:|---:|
| 8 nm | 1 | 1 | 1.5964% | 4 slices |
| 16 nm | 2 | 1 | 1.2875% | 3 slices |

The binary masks have Dice `0.8710` and IoU `0.7715`. The 8 nm profile is retained as the provisional review candidate because it follows the visible boundary more completely, but the skill deliberately requires human profile selection.

![8 nm MitoNet QC](qc-scale-8nm.png)

![16 nm MitoNet QC](qc-scale-16nm.png)

---

本示例使用 `mitonet-inference` Skill 对与 SegNeuron Pilot 相同的 Volume EM 小体积进行远程测试：

```text
syn178/raw[:18, :256, :256]
```

数据被准备为 `50 × 8 × 8 nm`、`18 × 128 × 128` (`zyx`) 的模型网格。远端使用官方量化 MitoNet-mini 权重、Empanada v0.1.7 commit `01c6e7aa3ad0e3c3334df8b129b0122724b6ad2e` 和 stack 模式。

8 nm 与 16 nm 两个候选均检测到同一个线粒体。8 nm 候选覆盖范围更完整，并多保留一个 z 切片，因此作为下一轮 Pilot 的暂定候选；Skill 不会根据对象数或前景比例自动选择 profile。

该结果证明远程部署、官方模型推理、三维匹配、provenance 和可视化流程可以端到端运行，但只有 18 个 z 切片、一个检测对象且没有 ground truth，不能视为科研准确率验证。

## Reproducibility / 可复现信息

- Model SHA-256: `80a16093026536850d661f3197f45c65535d35b2147efd959d2b26153a652505`
- Input SHA-256: `6b30bff65bcfe493e8260a982e323e9381e841bfb7ceff3b5fb89a6cfa6df839`
- 8 nm output SHA-256: `fcd4cd4885b16245da01decf02a1209cedfb89402c328db44348d6b701dce4f8`
- 16 nm output SHA-256: `3c650cb29d18b151e11a4c63bf6d2634d56e9f24550520fbd6736f375145d852`
- Common parameters: semantic threshold `0.3`, center threshold `0.1`, median kernel `3`, merge IoU/IoA `0.25/0.25`, minimum size `20`, minimum span `2`.

The model weights, source volume, credentials, environments, and large intermediate arrays are not stored in this repository.

模型权重、原始 volume、登录凭据、运行环境和大型中间数组不存放在本仓库中。
