---
name: charity-disclosure-checklist
description: 慈善组织/基金会/社会团体/社会服务机构的信息公开事项清单与法定依据速查。用于生成或查询应当公开的事项（61项分层）、对应法条依据条款号、法定时限与平台规则，或搭合规自查的清单框架。当用户只想要"该公开什么、依据哪条、什么时限"，或做信息公开合规自查/整改前先搭清单框架时使用。
version: "1.0.0"
display_name: 慈善组织信息公开清单与依据
display_name_en: Charity Disclosure Checklist & Legal Basis
description_zh: 一键获取基金会应公开事项清单、法条依据与时限要求
description_en: Get the full disclosure checklist, legal basis, and deadlines for charitable organizations.
---

# 慈善组织信息公开清单与依据

本技能是信息公开合规的"脊柱"：把一家慈善组织**应当公开什么、依据哪条、什么时限、走哪个渠道**一次说清。适合只想拿清单 / 依据 / 时限，不做评查、不写文稿的轻需求。

## 何时用本包
- 要一份可照着查的应公开事项清单（61 项分层版）
- 要某条义务的法条依据条款号与效力层级
- 要年度信息公开时限日历、阈值判定
- 搭合规自查框架的第一步（清单 + 责任分工）

## 本包含什么
| 文件 | 用途 |
|------|------|
| `references/spine/legal-basis.md` | 法定依据速查（法律/行政法规/部门规章/政策文件），含条款号与效力层级 |
| `references/spine/three-tier-checklist.md` | 依据与标准库：81 号令逐条义务总表 + 量化标准 + 罚则链条 / L2 平台规则 / L3 FTI 观测。**事项编号以 `templates/01` 为准** |
| `references/spine/platform-rules.md` | L2 层专册：慈善中国填报硬性要求 + 互联网募捐平台运营规则 |
| `references/spine/deadlines-and-thresholds.md` | 时限速查、阈值标准（重大慈善项目/主要捐赠人/重大资产变动）、不得公开信息与法律责任 |
| `templates/01-disclosure-checklist.md` | 信息公开全清单（分层版·61 项），事项编号唯一真源 |
| `templates/02-deadline-calendar.md` | 年度信息公开时限日历 |
| `templates/08-non-disclosure-record.md` | 不予公开判定记录表 |

## 关键作业步骤
1. **读依据**：`references/spine/three-tier-checklist.md`（事项与标准库）；**事项编号唯一真源是 `templates/01`**
2. **定时限**：`references/spine/deadlines-and-thresholds.md`
3. **补平台层**：`references/spine/platform-rules.md`（最易漏）
4. **出清单**：`templates/01` 分层全清单（L1 法定 53 / L2 平台 3 / L3 鼓励 4 / 非机构义务 1）
5. **核条款**：超出 references 覆盖范围或与用户材料冲突时，必须联网核对原文后再落笔

## 本包必守铁律
1. **条款号不得凭记忆书写**；81 号令条文号以 `three-tier-checklist.md` 总表为准，61 号令条款号已作废。
2. **三层不得混编**：L1 写"应当"、L2 写"平台要求"不写"依法"、L3 写"建议"不写"应当"；L3 不计入合规分母。
3. **效力分层**：只有法律/行政法规/部门规章/政策文件/政府公告可作正式义务依据；解读/指南/问答/标准/模板/案例/FTI 只能作参考并标注"非法律依据，仅供实务参考"。
4. **地方规则**：用户未明确地区只用全国性依据；明确地区后引用地方规则并标注"仅适用于该地区"。
5. **鼓励 ≠ 应当**：第十八条第二款、第二十九条为鼓励性规定，不得写成强制义务。
6. **不得编造数据、案例、处罚结果**；缺失信息写"待核实"或"未检索到明确依据"。
7. **机构名称必须用登记全称**检索；简称会混入大量无关主体。
8. 每次交付末尾附免责声明：本成果为合规参考，不构成正式法律意见。
