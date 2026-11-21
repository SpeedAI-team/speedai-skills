# 平台说明

## 降 AIGC 目标平台（humanize 的 `platform`）

| platform | 平台 | 说明 |
|---|---|---|
| `zhiwang` | 知网（CNKI） | 多数高校本科、硕博论文使用；默认值 |
| `weipu` | 维普 | 部分高校学位论文使用 |
| `weipu_qikan` | 维普期刊 | 期刊投稿检测 |
| `wanfang` | 万方 | 部分高校使用 |
| `gezida` | 格子达 | 不少本科院校使用 |
| `daya` | 大雅 | 部分院校使用 |
| `turnitin` | Turnitin | 英文论文、海外院校 |
| `gptzero` | GPTZero | 英文文本 |

`platform` 只对 `deai`、`deai_rewrite` 生效；`rewrite`（降重）与 `polish`（润色）忽略它。

## 检测平台（detect / 检测报告的 `platform`）

与 speedai.com 网页一致，只有三个：`zhiwang` 知网（默认）、`weipu` 维普、`turnitin` 国外（英文）。

## 选择建议

- 以学校或期刊通知里写明的检测系统为准；不确定时问用户，或默认 `zhiwang`。
- 降 AIGC 后尽量用同一个平台检测，前后对比才有意义：知网、维普直接对应；其他平台检测时用 `zhiwang`，英文用 `turnitin`。
- 英文段落降 AIGC 用 `turnitin` 或 `gptzero`，`lang` 填 `English`。
- 手上有学校检测系统出具的报告时，整篇文档可以附上报告（`report_*` / `--report`），只改标红段落：降 AIGC（`deai`）附 AIGC 检测报告，平台要与 `platform` 一致；降重（`rewrite`）附查重报告，知网 / 维普 / 格子达都可以。`platform` 为维普、维普期刊时用 .html，其他用 .pdf。

## 模式与计费（与 speedai.com 网页一致）

| mode | 作用 | 计费 |
|---|---|---|
| `deai` | 降 AIGC 率 | 每字 1 积分 |
| `rewrite` | 降重（默认深度降重，`deep: false` 关闭） | 每字 1 积分 |
| `deai_rewrite` | 降重 + 降 AIGC（默认深度模式，`deep: false` 关闭） | 每字 2 积分 |
| `polish` | 润色 | 每字 1 积分 |
| 检测 | 分段 AIGC 检测 | 每 10 字 1 积分，失败退回 |

实际扣费以 speedai.com 当前规则为准；单次文本上限 1,000 字。
