# 公益慈善机构治理与合规 · 技能集

> 一线公益从业者整理的 Agent Skills 集合。装的不是"一个人"，是一本本可以直接查的书。
> 覆盖：党建工作、关联交易、信息公开、理事会治理、项目与物资、志愿者与合作方、资质与财务、术语与规矩来龙去脉。

---

## 这是什么

这是 [Agent Skills](https://agentskills.io) 标准的技能包集合，可在 Claude Code、CodeBuddy、WorkBuddy、Cursor 等支持该标准的 Agent 中使用。
也可以当作纯资料读——每个技能的核心内容都在 `SKILL.md` 和 `references/` 里，都是中文的政策口径与实操清单。

**每个技能只做一件事，做完就走。** 不是聊天角色，不占对话，随问题自动被调用。

---

## 技能清单（21 个）

### 党建

| 技能 | 管什么 |
|---|---|
| [`annual-party-calendar`](skills/annual-party-calendar/) | 党建工作年度节奏与台账：按党组织形式裁剪年度任务，出 12 个月打钩表 |
| [`org-form-judgement`](skills/org-form-judgement/) | 党组织形式分型判定：先定 A/B/C/D/E 型，再谈年度任务 |

### 关联方与关联交易

| 技能 | 管什么 |
|---|---|
| [`related-party-identification`](skills/related-party-identification/) | 关联方识别与登记：谁能算关联方、怎么建台账 |
| [`related-party-transaction-review`](skills/related-party-transaction-review/) | 关联交易合规审查：哪些要审、审什么、怎么留痕 |
| [`related-party-disclosure`](skills/related-party-disclosure/) | 关联交易公开与责任：公开到什么程度、不公开什么后果 |

### 信息公开

| 技能 | 管什么 |
|---|---|
| `charity-disclosure` | 信息公开合规工具箱（索引型，指向下面几件） |

### 理事会治理

| 技能 | 管什么 |
|---|---|
| `foundation-council-compliance-check` | 理事会治理合规体检 |
| `foundation-council-transition` | 理事会换届全案 |
| `foundation-council-minutes-resolutions` | 理事会纪要与决议 |

> 注：这三件属于**收费档**，本仓库不收录。请在 [SkillHub](https://skillhub.cn) 获取。

### 项目、物资与受益人

| 技能 | 管什么 |
|---|---|
| [`gongyi-project-archive`](skills/gongyi-project-archive/) | 项目档案归集：八类清单与依据 |
| [`gongyi-beneficiary-registry`](skills/gongyi-beneficiary-registry/) | 受益对象管理 |
| [`gongyi-material-ledger`](skills/gongyi-material-ledger/) | 物资发放台账 |

### 志愿者与合作方

| 技能 | 管什么 |
|---|---|
| [`gongyi-volunteer-onboarding`](skills/gongyi-volunteer-onboarding/) | 志愿者招募培训与岗位适配 |
| [`gongyi-volunteer-roster`](skills/gongyi-volunteer-roster/) | 志愿者名册与服务记录证明 |
| [`gongyi-volunteer-safety`](skills/gongyi-volunteer-safety/) | 志愿者风险与保险 |
| [`gongyi-partner-onboarding`](skills/gongyi-partner-onboarding/) | 合作方准入与协议 |
| [`gongyi-cofundraising-check`](skills/gongyi-cofundraising-check/) | 合作募捐合规与对账 |

### 资质与财务

| 技能 | 管什么 |
|---|---|
| [`charity-qualification-registry`](skills/charity-qualification-registry/) | 资质名录本地查询库（八类资质，含 16752 家机构种子数据） |
| [`foundation-financial-statements`](skills/foundation-financial-statements/) | 三张报表解读 |
| [`foundation-income-tax`](skills/foundation-income-tax/) | 非营利组织收入税务判定 |
| [`foundation-charitable-trust`](skills/foundation-charitable-trust/) | 慈善信托与保值增值合规 |

### 术语、岗位与规矩

| 技能 | 管什么 |
|---|---|
| [`gongyi-term-lookup`](skills/gongyi-term-lookup/) | 慈善组织术语速查 |
| [`gongyi-role-lookup`](skills/gongyi-role-lookup/) | 岗位职责速查 |
| [`gongyi-rule-origins`](skills/gongyi-rule-origins/) | 规矩来龙去脉：这条规定为什么这么设、改过几次 |

### 通用

| 技能 | 管什么 |
|---|---|
| [`decision-bias-selfcheck`](skills/decision-bias-selfcheck/) | 决策偏误自查（不限于公益领域） |

### 等级评估（收费档，本仓库不收录）

`foundation-eval-indicator-breakdown`、`foundation-eval-onsite-interview`、`foundation-eval-self-assessment`、`foundation-eval-material-mapping`

请在 [SkillHub](https://skillhub.cn) 获取。

---

## 怎么用

### 方式一：当资料读

直接打开任意 `skills/<名字>/SKILL.md`，下面挂的 `references/` 是展开的清单和依据原文摘录。

### 方式二：装进 Agent

```bash
git clone https://github.com/Ella501528/gongyi-skills.git
cp -r gongyi-skills/skills/* ~/.claude/skills/        # Claude Code
# 或对应 Agent 的 skills 目录
```

⚠️ **技能在会话启动时扫描，装完要新开一个会话才能被发现。**

---

## 内容原则

这些技能是按"办事的人能照着干"写的，不是按"看起来专业"写的。具体说：

| 原则 | 体现 |
|---|---|
| **法规逐字核到款项号** | 每条判断都挂依据原文摘录，核不到标"待核"，不凭印象 |
| **留余地必须交代代价** | 讲"不受比例限制"时，一定接着说"年审年报评估一样会对照" |
| **分档要写清"含"** | "800 万元（含）到 6000 万元"，不写含糊的"800 万到 6000 万" |
| **不教人规避** | 不写"给你机会""不等于没关系" |
| **不装懂** | 专业之外只写"是什么／对我什么影响／我注意什么"，不写"怎么操作" |
| **主体范围开头交代** | 不在文末打补丁 |

---

## 说明与边界

- **不是法律意见。** 所有内容是从业经验与公开政策整理，具体口径**以最新官方现行文件和所属民政部门要求为准**。
- **案例已脱敏。** 涉及具体机构与人名的一律虚构或略去。
- **地名与机构名**：`charity-qualification-registry` 里的种子数据来自慈善中国等公开登记信息，仅作查询用。
- **收费档技能不在本仓库**，请到 SkillHub 获取。

---

## 相关

- 技能市场：[SkillHub](https://skillhub.cn)
- 技能标准：[Agent Skills](https://agentskills.io)

---

## 许可

本仓库内容以 **MIT** 协议开源，可自由使用、修改、再分发。
但请注意：**政策口径有时效性**，引用前请核对现行文件。
