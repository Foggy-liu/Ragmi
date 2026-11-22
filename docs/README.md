# docs/ 目录索引

> **接手项目先读**：根目录 `RULE.md`（协作规则 + 项目背景，**仅本地保留**）→ 本文件 → [status/项目现状.md](./status/项目现状.md)

本目录是**个人参考文档**，不是产品文档。上传仓库的只有本文件 + `plan/` + `status/`；
`note/` `task/` `personal/` `archive/` 只保留在本地。

---

## 目录结构

```
docs/
├── status/    # 现状快照 —— "现在到底长什么样"（以代码为事实）
├── plan/      # 设计 + 实施计划 —— "当时打算怎么做"
├── note/      # 笔记 —— "学到了什么 / 踩过什么坑"
├── task/      # 任务与提示词 —— "要做什么 / 原始对话"
├── personal/  # 面试与简历 —— 私人，不上传
└── archive/   # 已过时的历史版本 —— 只读，需要时从这里翻
```

| 文件夹 | 回答什么问题 | 上传 Git | 会不会过时 |
|---|---|---|---|
| `status/` | 现在系统是什么状态、还差什么 | ✅ | 会（每次改 agent 要同步） |
| `plan/` | 某次改动当时的设计与实施步骤 | ✅ | 不会（历史文档） |
| `note/` | 学习笔记、踩坑复盘、经验沉淀 | ❌ | 少 |
| `task/` | 待办问题集、原始设计对话、提示词记录 | ❌ | 会（做完了就归档） |
| `personal/` | 简历、岗位、面试准备 | ❌ | 与项目无关 |
| `archive/` | 被取代的旧版本 | ❌ | 不会 |

---

## status/ —— 现状（先读这里）

| 文件 | 内容 |
|---|---|
| [项目现状.md](./status/项目现状.md) | **主入口**。以当前代码为事实的全景：三层架构、Agent 四节点图、两计数器、工具状态、超时三层、9 字段 state、接口清单、问题清单 P0–P3 |
| [项目全景图.md](./status/项目全景图.md) | 代码全景地图：建议阅读顺序 + 数据流 + 14 条不变量 + 风险地图 |
| [项目能力与边界.md](./status/项目能力与边界.md) | **回答"这项目最终能做到什么程度"**：已做到的 12 条（带证据）/ 量化边界 / 明确做不到的 10 条 / 生产化还差几项 / 面试自述脚本 |
| [项目优化.md](./status/项目优化.md) | 优化记录流水（O-001 ~ O-006），每项含改动清单 + 验证结果 + 遗留。`gitignore` 级别敏感，含内部数字 |
| [工业化评估与遗留清单.md](./status/工业化评估与遗留清单.md) | 2026-11-15 的工业化评估：7 个问答 + 3 个实测探针，产出遗留清单 |
| [测试现状.md](./status/测试现状.md) | **2026-11-18 按测试类型重写**：单元/流程/接口/集成/端到端/性能六类分类 + 每类的实测结果 + §2 指标定义（怎么衡量一个机制）+ §3 实测明细 + **§4 明确没有的测试（8 条诚实缺口）** |
| [测试体系.md](./status/测试体系.md) | 4 层测试体系的**设计**（怎么造假的、为什么这么分层） |

> 改 `agent/` 行为后，**先更新 `status/项目现状.md`**，否则它就成了下一个谎言。

## plan/ —— 设计与实施计划（历史）

| 文件 | 内容 |
|---|---|
| [v2.2-graph-design.md](./plan/v2.2-graph-design.md) | v2.2 四节点图设计（拆分 iter/synth 的理由） |
| [v2.2-graph-impl.md](./plan/v2.2-graph-impl.md) | v2.2 实施步骤（最大的一份） |
| [v2.2-handover.md](./plan/v2.2-handover.md) | v2.2 交接单：6 个待拍板问题 |
| [v2.1-reflection.md](./plan/v2.1-reflection.md) | v2.1 反思机制设计与实施 |
| [metadata-citation-design.md](./plan/metadata-citation-design.md) / [metadata-citation-impl.md](./plan/metadata-citation-impl.md) | 元数据引用（溯源）设计与实施 |
| [repair-closeout-design.md](./plan/repair-closeout-design.md) / [repair-closeout-impl.md](./plan/repair-closeout-impl.md) | 收尾修复批次 |
| [test-plan-l0-l4.md](./plan/test-plan-l0-l4.md) | L0–L4 分层测试计划 |

> 这批文件原在 `docs/superpowers/`，本轮重组时改名去掉了 `specs/` `plans/` 前缀。

## note/ —— 笔记（16 篇）

**Agent 概念学习**：`agent_guide.md`（基础概念）→ `agent_note_01_handwritten_to_langgraph.md`（手写 vs LangGraph）→ `agent_note_02_agent_patterns.md` → `agent_note_03_react_deep_dive.md` → `agent_note_04_self_reflection.md` → `agent_note_05_reflection_audit.md`

**工程实践**：`agent项目搭建.md`（搭建过程）· `controller_lessons.md`（旧架构反思）· `工具批数与超时机制.md` · `超时与异常机制设计.md` · `m2_ingest_pipeline_fix_log.md` · `model_switch_2026_11_10.md` · `终端快捷命令.md` · `项目领域耦合.md`

**学习日志**：`agent_learning_log.md` · `agent_v2_learning_log.md`

## task/ —— 任务与提示词

| 文件 | 内容 |
|---|---|
| [开场提示词.md](./task/开场提示词.md) | **下次开 Claude Code 直接粘这段** —— 一句话让它读懂当前项目状态 |
| [agent-v2.2-design-dialog.md](./task/agent-v2.2-design-dialog.md) | v2.2 设计期的完整对话记录（决策来龙去脉） |
| [agent问题集.md](./task/agent问题集.md) | 待解决问题清单 |
| [prompts-2026-08-to-11.md](./task/prompts-2026-08-to-11.md) | 2026-08 ~ 11 的提示词存档 |

## personal/ —— 私人（用户自己维护）

`招聘.md`（目标岗位）· `简历.md` · `项目.md` · `项目测试面试准备.md` · `项目面试评估.md` + 简历 PDF/DOCX。

> 本轮**未改动**该目录，由用户自行处理。

## archive/ —— 已被取代的旧版本

| 文件 | 内容 | 为什么还留着 |
|---|---|---|
| [ragmi_project_manual.md](./archive/ragmi_project_manual.md) | v1 时代全项目说明书 | 讲的是已删掉的 v1 架构，只作历史参照 |
| [2026-07-08-pre-v2.1.md](./archive/2026-07-08-pre-v2.1.md) | v2.1 之前的架构快照 | 历史版本 |
| [postman-运行结果-2026-07-08.md](./archive/postman-运行结果-2026-07-08.md) | Postman 4 个 case 的真实 API 响应（含 `<think>` 原文、耗时） | 讲"v1 的思考过程长什么样"要用 |

> 原 `项目状态-2026-11-10.md`（2026-11-10 的现状快照）已于 2026-11-15 **合并进
> [status/项目现状.md](./status/项目现状.md) 并删除** —— 里面的 RAG 侧分析（摄取/检索链路、
> LangChain 组件清单、存储与框架选型、模型配置、部署、前端与依赖注入）经代码复核后全部并入，
> Agent 部分按 2026-11-15 的代码重写。

---

## 找到东西的路径

| 我想…… | 去哪 |
|---|---|
| 看系统现在是什么样 | `status/项目现状.md` |
| 看代码怎么串起来的 | `status/项目全景图.md` |
| 搞懂某次改动为什么这么设计 | `plan/` 对应文件 |
| 查某个坑的来龙去脉 | `note/` + `task/agent-v2.2-design-dialog.md` |
| 搞清测试到底测了什么、跑得通吗 | `status/测试现状.md`（+ `test/README.md`） |
| 这项目到底能做到什么程度 | `status/项目能力与边界.md` |
| 准备面试讲什么 | `personal/` + `archive/postman-运行结果-2026-07-08.md` + `status/项目能力与边界.md` §6 |
| 找被淘汰的旧实现 | `archive/` |

---

## 维护约定

1. `status/项目现状.md` 是**唯一**的现状真相来源，改代码后同步它。
2. 设计文档写完就冻结，不回改 —— 改了就不是历史了。
3. 过时的东西**移进 `archive/`** 而不是删（除非确认无价值），文件名带日期。
4. 私人内容（简历、面试、对话记录）留在 `personal/` `task/`，不上传。
5. `docs/` 下的文件 **不要** 放代码能直接表达的信息。
