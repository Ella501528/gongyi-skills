---
name: charity-disclosure-remediation
description: 慈善组织信息公开自评与整改。用于对照清单做合规自查打分、诊断缺口（红/黄/提升三级）、生成整改台账与分级整改行动方案，并含 FTI 公开度自评水位。当用户要做内部合规体检、出整改方案、迎检准备或补公开时使用。
version: "1.0.0"
display_name: 慈善组织信息公开自评与整改
display_name_en: Charity Disclosure Self-Assessment & Remediation
description_zh: 对照清单自评、诊断缺口并生成整改方案
description_en: Self-assess against the checklist, diagnose gaps, and produce a remediation plan.
---

# 慈善组织信息公开自评与整改

本技能聚焦"内部合规体检"：对照清单自查打分、诊断缺口、出整改台账与行动方案。适合机构自己查缺补漏、迎检准备、补公开的需求。

## 何时用本包
- 做内部合规自查 / 迎检准备
- 对照清单诊断缺口（红/黄/提升三级）
- 生成整改台账与分级整改行动方案
- FTI 公开度自评与精进

## 本包含什么
| 文件 | 用途 |
|------|------|
| `references/spine/legal-basis.md` | 法定依据速查 |
| `references/spine/three-tier-checklist.md` | 事项与标准库（自评对照真源） |
| `references/spine/platform-rules.md` | 平台规则 |
| `references/spine/deadlines-and-thresholds.md` | 时限与阈值 |
| `references/maturity/fti-benchmark.md` | L3 层专册：FTI 规则、指标体系、行业水位、使用禁忌 |
| `templates/01-disclosure-checklist.md` | 信息公开全清单（分层版·61 项），自评对照真源 |
| `templates/06-self-audit-scorecard.md` | 信息公开合规自查打分表（内部） |
| `templates/07-remediation-log.md` | 整改台账 |
| `templates/10-maturity-scorecard.md` | FTI 公开度自评与精进表（仅内部） |
| `templates/13-gap-diagnosis.md` | 缺口诊断表·三级（🔴红/🟡黄/⚪提升） |
| `templates/14-remediation-plan.md` | 整改行动方案（分级 + 责任 + 排期） |

## 关键作业步骤
1. **读依据与清单**：`references/spine/*` + `templates/01`
2. **自查打分**：`templates/06`（内部问"你履行了没有"）
3. **诊断缺口**：`templates/13`（🔴红线/L1未公开或超期 / 🟡黄线/要素偏差 / ⚪提升/L2L3未做）
4. **出方案**：`templates/14` + 整改台账 `templates/07`；FTI 自评加 `templates/10`
5. **核条款**：超出 references 覆盖范围必须联网核对原文

## 本包必守铁律
1. **内部自查 ≠ 外部评查口径**：自查打分（`templates/06`）问"你履行了没有"；不得把内部口径套到外部评查上。
2. **内部自持材料不是公开证据**：盘家底结论不得回填公开状态、不得进评分。
3. **FTI 只观测基金会**：社团与民非不适用；FTI 是 D 级证据，不作"已公开"证明，也不作机构整体评价背书。
4. **鼓励 ≠ 应当**：第十八条第二款、第二十九条为鼓励性规定，不得写成强制义务；L3 不计入合规分母。
5. **条款号不得凭记忆书写**；81 号令条文号以 `three-tier-checklist.md` 总表为准，61 号令已作废。
6. **三层不得混编**：L1 写"应当"、L2 写"平台要求"不写"依法"、L3 写"建议"不写"应当"。
7. **不得编造数据、案例、处罚结果**；缺失信息写"待核实"或"未检索到明确依据"。
8. 每次交付末尾附免责声明：本成果为合规参考，不构成正式法律意见。
