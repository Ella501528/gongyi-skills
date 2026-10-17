---
name: charity-qualification-registry
description: "慈善领域各类资质名录的本地查询库：慈善组织登记认定、公开募捐资格、公益性捐赠税前扣除资格、非营利组织免税资格、社会组织评估等级、活动异常名录与严重违法失信名单等。当需要查某家基金会/社会团体/社会服务机构有没有某项资质、某项资质的最新名单里有没有它、它是否被列入异常名录或严重违法失信名单、某项资质在哪个年度批次内有效时使用。也用于把名录批量导出、比对某一批机构名单、跟踪名单的增删变化。"
version: "1.0.0"
slug: charity-qualification-registry
displayName: 慈善组织资质名录库
summary: 慈善领域八类资质名录的本地可查库，支持自动抓取更新与变更追踪。
tags: [慈善资质, 公开募捐资格, 税前扣除资格, 免税资格, 评估等级, 异常名录, 名录库]
license: MIT
display_name: "慈善组织资质名录库"
display_name_en: "Charity Qualification Registry"
description_zh: "把散在慈善中国、财政税务民政公告里的各类慈善资质名单收进一个本地库，随时可查、可更新、可看变化。"
description_en: "A local queryable registry of charity-sector qualification lists, aggregated from the national charity information platform and government announcements, with automatic updates and change tracking."
agent_created: true
---

# 慈善资质名录库

把散落在多个官方渠道的慈善资质名单，收进一个**本地 SQLite 库**，支持随时查询、定期更新、追踪变化。

## 它是什么、不是什么

| | 说明 |
|---|---|
| **是** | **名录库**——记录「谁有某项资质」「谁被取消了」「谁进了异常名录」，以及这些状态随时间的变化 |
| **不是** | 办理指南。某项资质怎么办、要什么材料、怎么维持，不属于本库范围 |

一句话区分：本库回答**「这家机构有没有」**，不回答**「我该怎么办」**。

## 覆盖的名录

| 编号 | 名录 | 数据源 | 状态 |
|---|---|---|---|
| R1 | 慈善组织登记认定名录 | 慈善中国 | ✅ 已实现 |
| R2 | 公开募捐资格名录 | 慈善中国 | ✅ 已实现 |
| R3 | 公益性捐赠税前扣除资格名单 | 财政部／税务总局／民政部公告 | ✅ 已实现 |
| R4 | 非营利组织免税资格名单 | 省级财政／税务／民政 | 规划中 |
| R5 | 社会组织评估等级（3A 及以上） | 省市民政部门公告 | 规划中 |
| R6 | 活动异常名录／严重违法失信名单 | 慈善中国 | ✅ 已实现 |
| R7 | 慈善信托备案名录 | 慈善中国 | 规划中 |
| R8 | 互联网公开募捐服务平台名单 | 民政部公告 | 规划中 |

R6 是负向名单，用于尽职调查时排查风险机构，价值最高。

## 快速开始

```bash
cd scripts

# 首次使用：若本包 data/ 下带有种子数据，第一次运行任一命令时会自动生成 cqr.db；
# 若未带种子数据，请先执行下方的 update 抓取，再查询。
# （如需重建空库，执行 python cqr.py init）

# 更新全部已实现名录（首次建议按 R6 → R2 → R3 顺序）
python cqr.py update --only R6
python cqr.py update --only R2
python cqr.py update --only R3

# 查单个机构
python cqr.py query --name "<机构名称关键词>"
python cqr.py query --uscc "<18 位统一社会信用代码>"

# 拉清单（按资质类型）
python cqr.py list --qual R2 --limit 50                # 有公募资格的机构
python cqr.py list --qual R2 --region 北京              # 再加地区条件
python cqr.py list --qual R6                           # 异常名录／严重失信名单
python cqr.py list --qual R2 --status 注销              # 已注销但仍有记录的
python cqr.py list --qual R2 --export 名单.csv          # 导出全部

# 库统计 / 查看变更
python cqr.py stats
python cqr.py changes --limit 50
```

### 资质编号

`R1` 慈善组织登记认定　`R2` 公开募捐资格　`R3` 公益性捐赠税前扣除资格
`R6` 信用状况（活动异常名录／严重违法失信名单）

> R6 的 `has_flag=1` 表示**在负面名单内**，与其他资质的语义相反，使用时须注意。

## 依赖

- Python 3.10+
- `playwright`（抓取慈善中国，需要 Chromium 内核）、`httpx`（抓取公告页）、`numpy`、`Pillow`（滑块验证求解）
- 首次运行抓取前需执行 `playwright install chromium`

## 可信度边界（重要）

1. **本库是线索库，不是权威结论。** 出具正式意见前，须回到源站页面或公告原文核验。
2. **每条资质记录都保留来源与原始凭证。** 用 `query` 查看时，记录里的「来源」字段即出处；公告类记录另存文号。
3. **第三方机构名录存在口径差异。** 慈善中国展示的「是否具有公开募捐资格」「是否取得公益性捐赠税前扣除资格」以该平台公示为准；财政部等三部门公告为资格认定的原始依据。两者不一致时以公告为准并记录差异。
4. **名称匹配存在局限。** 公告名单以机构全称列出，按名称精确匹配。机构改名的，历史记录可能落在旧名下。

## 已知限制

- **反爬**：慈善中国对列表页与详情页做滑块校验。本库自带求解流程，多数情况 1–3 次尝试内通过；失败时脚本会明确报错，不会静默返回空数据。
- **无官方接口**：全部数据来自页面抓取。源站改版会导致抓取失效，此时需更新本 skill 的解析逻辑。
- **业务主管单位**：慈善中国不提供该字段。需要时须另查社会组织登记信息。
- **省级名录**：R4／R5 各地公告格式不统一，实现成本高，尚未纳入。

## 抓取礼仪

- 默认限速 0.8 秒／页，可通过环境变量 `CQR_PACE` 调整。
- 脚本不并发、不重试轰炸；单次全量抓取约数分钟。
- 仅采集公开披露信息，不采集任何非公开数据，不使用任何账号登录态。

## 文件结构

```
charity-qualification-registry/
├── SKILL.md
├── scripts/
│   ├── cqr.py                 命令行入口
│   ├── fetch_cszg.py          慈善中国抓取（R1/R2/R6）
│   ├── fetch_tax.py           财税公告抓取（R3）
│   └── core/
│       ├── db.py              存储层（SQLite schema）
│       └── session.py         浏览器会话与滑块处理
├── data/
│   ├── seed_org.csv           种子数据·机构主表（体积受限的发布渠道不附）
│   ├── seed_qual.csv          种子数据·资质表（体积受限的发布渠道不附）
│   └── cqr.db                 名录库（首次运行时若有种子数据则自动生成）
└── references/
    ├── 数据源说明.md
    └── 字段口径.md
```

## 库结构

| 表 | 内容 |
|---|---|
| `org` | 机构主表：名称、统一社会信用代码、组织类别、登记管理机关、状态、信用状况 |
| `qual` | 资质表：机构 × 资质类型，含是否具有、有效期、来源、原始凭证 |
| `snapshot` | 快照表：按批次保留历史值，用于比对 |
| `changelog` | 变更日志：新增／失效／值变更／移出名单 |

## 更新机制

- **慈善中国类（R1/R2/R6）**：名单随时变动，建议每周更新一次。R6 规模小（不足百条），每次全量刷新即可。
- **公告类（R3）**：一年发布 1–2 批，建议每月检查一次，有新公告时更新。
- 每次更新都会自动比对上次结果，增删变化写入 `changelog`，用 `cqr.py changes` 查看。
