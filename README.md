# Webdev Result Evolution Agent

---

## 🚀 初次使用？

**建议直接阅读 [QUICKSTART.md](QUICKSTART.md)，5 分钟完成上手，无需通读本文档。**

---

一个面向 **Web 前端评估体系迭代**的分析 Agent：上传人工 Ground Truth 和自动评估 Auto Eval 两份 Excel → Agent 自动对齐数据、计算偏差指标、调用大模型生成根因分析 → 输出 Skill 优化建议、策略建议、权重方案，并导出完整的多 Sheet Excel 报告。

```
┌── 前端 (frontend/index.html，单文件 SPA) ───────────────────────────┐
│  新建任务 · 维度检查 · 指标看板 · 差异样本 · 优化建议 · 任务历史     │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ REST API
┌──────────────────────▼─── 后端 (FastAPI, port 8001) ───────────────┐
│  parsers/   表头自动识别：22 维度 + 样本 ID 字段                    │
│  core/      数据对齐 → 指标计算（确定性，LLM 不参与）               │
│  advisors/  Skill 建议 + 策略建议 + 权重方案 A/B/C                  │
│  llm/       LLM 网关客户端（ERNIE / Anthropic / OpenAI / Mock）     │
│  reports/   8-Sheet Excel 报告生成                                   │
│  services/  任务管理 + 异步分析流水线                               │
└────────────────────────────────────────────────────────────────────┘
数据库：SQLite（data/evolution.db）
配置：config/dimensions.yaml + config/weights.yaml
```

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- macOS / Linux（Windows 未测试）

### 2. 启动服务

```bash
cd "Webdev_result_evolution Agent"
./run.sh
```

`run.sh` 会自动完成：创建 `.venv` 虚拟环境 → 安装依赖 → 启动服务。

启动成功后打开浏览器访问：`http://127.0.0.1:8001`

### 3. 配置大模型（可选）

默认以 `PROVIDER=mock` 运行（无需 Key，LLM 建议为固定测试文本），基础指标仍然完整计算。

复制并编辑 `.env`：

```bash
cp .env.example .env
```

根据你的大模型服务填写对应字段：

**百度 ERNIE / OneAPI 内网网关（推荐）**
```
PROVIDER=ernie
ERNIE_ENDPOINT=https://你的内网网关地址/v1
ERNIE_TOKEN=sk-你的Token
ERNIE_MODEL=gpt-5.5
```

> **⚠️ 网关地址、Token 及可用模型列表见内网 OneAPI 及相关文档。常用模型：`gpt-5.5` /  `deepseek-v4-flash`**

> **注意**：`ERNIE_ENDPOINT` 只填到 `/v1` 层，系统会自动拼接 `/chat/completions`。
> 修改 `.env` 后需重启服务才能生效。


**Anthropic Claude**
```
PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-你的Key
ANTHROPIC_MODEL=claude-opus-4-8
```

**OpenAI**
```
PROVIDER=openai
OPENAI_API_KEY=sk-你的Key
OPENAI_MODEL=gpt-4o
```


---

## 输入文件要求

### Ground Truth（人工评分表）

Excel 文件（`.xlsx`），每行一条样本×模型的评分记录，列需包含：

| 列名参考 | 逻辑字段 | 说明 |
|---|---|---|
| `model_id` / `candidate_model` / `模型` | 候选模型 | 必须，用于对齐 |
| `data_id` / `数据id` | 数据 ID | 推荐，用于对齐 |
| `query_id` / `问题id` | 问题 ID | 推荐，用于对齐 |
| `query` / `问题` | 题目文本 | 可选，展示用 |
| `response` / `url` / `eval_url` | 评估链接 | 可选，展示用 |
| `bridge_url` | 桥接 URL | 可选 |
| `G1`、`F1`、`I1`… | 各维度评分列 | 核心字段，值为 0/1/2（Gateway 维度为 0/1）|

> **列名识别规则**：系统用模糊子串匹配，列名含维度代码（如 `G1`、`F1`）或维度中文名（如 `推理与部署`、`功能逻辑`）均可识别。豁免/不适用填写 `豁免`、`exempt`、`N/A` 均可。

### Auto Eval（自动评估结果表）

格式要求与 GT 相同，额外支持：

| 列名参考 | 逻辑字段 | 说明 |
|---|---|---|
| `reason` / `auto_reason` / `原因` | 自动评分原因 | 可选，LLM 归因时参考 |

---

## 完整操作流程

### Step 1：新建任务

在「新建任务」页面填写：

- **任务名称**（必填）
- **批次**（可选，如 `2025-06-25`）
- **Judge 模型**（必填，选择本次评估使用的自动评分模型）
- **版本信息**：Skills 版本、Rubric 版本、权重版本（可选）
- **上传 GT 文件**（点击或拖拽 `.xlsx`）
- **上传 AutoEval 文件**（点击或拖拽 `.xlsx`）

点击「创建并分析」后，系统自动依次执行：上传文件 → 维度检查 → 异步分析，完成后跳转到指标看板。

### Step 2：维度检查（自动）

系统检查三项：

1. **文件格式检查**：能否正常读取、是否有表头
2. **维度对齐检查**：GT 和 AutoEval 中识别到的维度是否一致，标注新增/缺失/疑似匹配
3. **样本对齐检查**：两份文件的样本数、模型数、key 重复情况

如检查发现维度不对齐（如列名写法不同），可在「维度检查」页面手动配置映射后再分析。

### Step 3：数据对齐与指标分析

对齐键：`data_id + query_id + candidate_model + dimension_code`（四级降级匹配）

每条对齐记录包含：

| 字段 | 说明 |
|---|---|
| `data_id` / `query_id` / `candidate_model` | 样本标识 |
| `query` / `response` / `bridge_url` | 样本上下文 |
| `dimension_code` | 评分维度代码 |
| `ground_truth_score` | 人工 GT 分值 |
| `auto_score` | 自动评分分值 |
| `delta` | auto - gt，正值=偏高，负值=偏低 |
| `auto_reason` | 自动评分理由 |
| `gt_is_valid` / `auto_is_valid` | 是否为合法评分 |
| `gt_is_exempt` / `auto_is_exempt` | 是否豁免 |
| `has_auto` | AutoEval 是否有对应记录 |

**数据质量统计**（在 overall 指标 `data_quality` 字段中）：

| 统计项 | 说明 |
|---|---|
| `matched_cells` | GT 与 Auto 成功匹配的评分格数 |
| `gt_only_cells` | GT 有但 AutoEval 无的记录（整行缺失） |
| `auto_only_cells` | AutoEval 有但 GT 无的多余记录数 |
| `missing_auto_cells` | 匹配到行但 AutoEval 评分为空（漏评） |
| `illegal_score_cells` | 分值超出合法范围（非法评分） |
| `exempt_cells` | 标记为豁免/不适用的记录数 |

### Step 4：指标看板

「指标看板」展示：

**整体指标**
- 有效评分格数 / 理论格数 / 覆盖率
- 精确一致率（exact match）
- ±1 一致率（within1）
- 平均绝对误差（MAE）
- 系统性偏差（Bias，正=偏高，负=偏低）
- 严重误判率（GT=0↔Auto=2 的翻转比例）
- Macro F1 / Weighted F1

**分类指标**：Functionality / Interactivity / Aesthetics / Content / DataPersistence 各类别独立统计

**维度指标**：22 个维度（G1-G4 / F1-F4 / I1-I4 / A1-A4 / C1-C2 / DP1-DP4）各自的精确一致率、Bias、MAE

**模型指标**：各候选模型的各项指标对比

### Step 5：差异样本明细

「差异样本」页面列出 GT 与 AutoEval 不一致的所有记录，支持：

- **维度筛选**：按具体维度查看
- **严重误判筛选**：仅显示 |delta| = 2 的翻转样本
- **分页浏览**：顶部和底部均有翻页控件

### Step 6：优化建议

「优化建议」包含三个 Tab：

**Skill 建议**：针对精确一致率 < 70% 的维度，指出偏差方向（偏高/偏低/随机），并生成**优化后的完整新评分标准**（含校准建议和豁免条件）。配置了真实 LLM 时附带 LLM 根因总结。

**策略建议**：针对 Bias 显著维度或整体偏差，给出评估流程层面的建议

**权重建议**：输出三套权重方案：
- 方案 A：保守归一化（仅修正合计不等于 100 的问题）
- 方案 B：业务平衡（功能/交互权重小幅上调）
- 方案 C：数据驱动（一致率越低的类别获得越高权重，代表更需优先校准）

> **注意**：所有建议均为候选，系统**不会自动修改任何配置**，需人工确认后手动应用。

### Step 7：导出报告

点击「导出报告」按钮，系统生成 Excel 文件（8 个 Sheet）：

| Sheet | 内容 |
|---|---|
| 00_任务摘要与整体指标 | 任务元信息、数据质量统计、整体指标（精确一致率/Bias/MAE/F1 等）|
| 01_分类指标 | 各类别（Functionality/Interactivity/Aesthetics/Content/DataPersistence）详细指标 |
| 02_逐维度指标 | 22 维度各自的精确一致率、MAE、Bias、严重误判率 |
| 03_模型指标 | 各候选模型的指标对比，有效格率 <50% 的模型行标红 |
| 01_差异样本明细 | 所有记录明细（含差异、空值、豁免），GT 分/Auto 分/Delta/归因/理由 |
| 05_Skill优化建议 | 维度级优化建议，含建议文字、优化后完整评分标准、LLM 总结 |
| 06_策略优化建议 | 评估流程策略建议 |
| 07_权重调整建议 | 三套权重方案（A/B/C）对比，含当前/建议/变化量 |

文件名格式：`Webdev_result_evolution_Report_{任务名}_{时间}.xlsx`

---

## 配置说明

### 评分维度（config/dimensions.yaml）

定义 22 个评分维度，每个维度包含：

```yaml
- code: F1
  category: Functionality
  name: 功能逻辑正确
  layer: scoring           # gateway（门槛层）或 scoring（评分层）
  scale: "0/1/2"           # 评分量表
  automatable: false       # 是否可自动化评估
  eval_type: 客观评估（人工）
  exemption: 暂无豁免。
  rubric_points: |
    评分参考：0 分=...
```

**门槛层（Gateway）**：G1-G4，评分为 0/1，任一维度为 0 则该样本综合分为 0。

**评分层**：F1-F4 / I1-I4 / A1-A4 / C1-C2 / DP1-DP4，评分为 0/1/2。

### 类别权重（config/weights.yaml）

```yaml
category_weights:
  Functionality: 31
  Interactivity: 28
  Aesthetics: 31
  Content: 12
```

合计建议为 100。可在前端「⚖️ 权重配置」页面直接编辑并保存，或上传 YAML/Excel 文件覆盖。

> 当前默认权重（F31/I28/A31/C12）由人工标注样本反推，Bias 显著的维度建议参考 Agent 的权重方案 C 调整。

### Skills 定义

前端「⚙️ Skills」页面可查看和编辑所有 22 个维度的完整定义（含 rubric_points 评分标准和 exemption 豁免条件），支持以下两种方式上传批量更新：

- **YAML 文件**（`.yaml` / `.yml`）：与 `config/dimensions.yaml` 格式相同
- **Markdown 文件**（`.md`）：支持 WebDev 评测维度说明标准格式，`##` 章节标题识别类别，`###` 标题识别维度代码，`**评分标准**` 和 `**豁免规则**` 段落自动提取

**任务级 Skills**：新建任务时可额外上传 Skills 文件，仅对该任务生效，优先级高于全局配置。

---

## 评分层偏差分析说明

### 指标计算原则

**所有评估指标由确定性代码计算，LLM 只参与文字归因总结，不影响任何数值。**

- **有效评分格**：GT 和 Auto 双方均有合法分值（在 score_range 内）且均未标记豁免
- **理论格数** = `DataAligner.align()` 输出的总记录条数（GT 样本数 × GT 识别到的维度数）
- **无效评分格** = 理论格数 − 有效评分格数，包含：空值格、豁免格、非法评分格
- **覆盖率** = 有效评分格数 / 理论格数
- **Bias**：正值表示 AutoEval 系统性偏高（偏乐观），负值表示偏低（偏严格）
- **严重误判**：GT=0 且 Auto=2，或 GT=2 且 Auto=0 的翻转样本

### LLM 调用时机

仅在以下场景调用 LLM：

1. 维度精确一致率 < 70%（问题维度）时，调用 LLM 生成中文根因总结（注入对应维度 rubric_points 作为上下文）
2. 生成 Skill 建议 LLM 总结文字

**LLM 调用失败时**（网络超时、Key 无效等），系统自动降级：指标正常输出，LLM 总结字段为降级提示文本，不影响报告生成。

重试机制：`LLM_MAX_RETRIES=3`，指数退避（1s/2s/4s）。

---

## 已知限制与注意事项

1. **Auto Only 独有行**：DataAligner 以 GT 为主表做左连接，AutoEval 中有但 GT 中没有的行在对齐后不进入指标计算（`auto_only_cells` 单独统计）。
2. **列名识别**：使用子串模糊匹配，`model_id` 会被识别为 `candidate_model`（非 `data_id`），这是设计行为。如识别错误，在维度检查页面手动修正映射。
3. **多 Sheet GT**：当前只读取第一个非空 Sheet。多 Sheet 场景请提前合并。
4. **合并单元格**：`FileParser` 会展开合并单元格，但嵌套合并格式可能解析异常，建议上传前取消合并。
5. **PROVIDER 环境变量**：修改 `.env` 后必须重启服务，`python-dotenv` 仅在进程启动时加载。
6. **建议仅为候选**：所有 Skill 建议、权重方案均为参考，系统不会自动写回任何配置，需人工确认。
7. **GT 文件只读**：分析过程不修改任何输入文件。

---

## 目录结构

```
Webdev_result_evolution Agent/
├── backend/
│   ├── main.py                # FastAPI 入口，路由注册
│   ├── config.py              # 环境变量读取
│   ├── models.py              # SQLAlchemy 模型 + Pydantic DTO
│   ├── parsers/
│   │   ├── file_parser.py     # Excel 读取，合并单元格展开
│   │   ├── schema_detector.py # 表头字段识别（样本字段 + 维度字段）
│   │   └── dimension_matcher.py  # 维度代码对齐
│   ├── core/
│   │   ├── data_normalizer.py # 转长表 + GT/AutoEval 对齐（DataAligner）
│   │   ├── metric_engine.py   # 所有确定性指标计算
│   │   ├── error_clusterer.py # 规则归因 + LLM 总结
│   │   └── weight_validator.py
│   ├── advisors/
│   │   ├── skill_advisor.py   # Skill 优化建议
│   │   ├── strategy_advisor.py
│   │   └── weight_advisor.py  # 三套权重方案 A/B/C
│   ├── llm/
│   │   └── gateway_client.py  # LLM 统一网关（ERNIE/Anthropic/OpenAI/Mock）
│   ├── reports/
│   │   └── report_generator.py  # 11-Sheet Excel 报告
│   ├── routers/
│   │   ├── tasks.py           # 任务相关 REST API
│   │   └── config_api.py      # Skills / 权重配置 API
│   └── services/
│       └── analysis_runner.py # 异步分析流水线
├── frontend/
│   └── index.html             # 单文件 SPA（纯 HTML/CSS/JS）
├── config/
│   ├── dimensions.yaml        # 22 个评分维度定义
│   └── weights.yaml           # 类别权重配置
├── data/
│   ├── uploads/               # 上传的原始文件
│   ├── reports/               # 导出的 Excel 报告
│   ├── logs/                  # 运行日志
│   └── evolution.db           # SQLite 数据库
├── .env                       # 本地环境变量（不提交 git）
├── .env.example               # 环境变量模板
├── requirements.txt
└── run.sh                     # 一键启动脚本
```

---

## API 一览

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/tasks` | 创建任务 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情 |
| POST | `/api/tasks/{id}/upload/ground_truth` | 上传 GT 文件 |
| POST | `/api/tasks/{id}/upload/auto_eval` | 上传 AutoEval 文件 |
| POST | `/api/tasks/{id}/check` | 执行维度/样本检查 |
| GET | `/api/tasks/{id}/check-result` | 获取检查结果 |
| POST | `/api/tasks/{id}/dimension-mapping` | 保存手动维度映射 |
| POST | `/api/tasks/{id}/analyze` | 触发异步分析 |
| GET | `/api/tasks/{id}/status` | 任务状态 |
| GET | `/api/tasks/{id}/metrics` | 指标结果 |
| GET | `/api/tasks/{id}/differences` | 差异样本（分页 + 筛选）|
| GET | `/api/tasks/{id}/recommendations` | 优化建议 |
| GET | `/api/tasks/{id}/weight-simulations` | 权重模拟 |
| POST | `/api/tasks/{id}/export` | 生成 Excel 报告 |
| GET | `/api/tasks/{id}/download-report` | 下载报告文件 |
| GET | `/api/config/skills` | 获取 Skills 配置 |
| POST | `/api/config/skills` | 保存 Skills 配置 |
| POST | `/api/config/skills/upload` | 上传 Skills 文件 |
| GET | `/api/config/weights` | 获取权重配置 |
| POST | `/api/config/weights` | 保存权重配置 |
| POST | `/api/config/weights/upload` | 上传权重文件 |

---

## 常见问题

**Q：分析完成后建议里 `llm_summary` 是固定的 Mock 文本**

A：当前 `PROVIDER=mock` 或大模型配置未生效。检查 `.env` 中 `ERNIE_ENDPOINT` 是否为真实地址，修改后重启服务。可用以下命令快速验证网关连通：

```bash
curl -X POST "$ERNIE_ENDPOINT/chat/completions" \
  -H "Authorization: Bearer $ERNIE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"test"}],"max_tokens":10}'
```

**Q：上传文件后维度识别为空**

A：检查列名是否包含维度代码（G1/F1/I1 等）或中文名（推理与部署/功能逻辑等），或使用维度检查页的手动映射功能。

**Q：历史任务状态停留在 `analyzing`**

A：进入任务历史页面时系统会每 3 秒自动刷新状态。如长时间不变化，查看服务端日志（`/tmp/evolution_server.log`）确认后台是否有报错。

**Q：覆盖率很低（如 50%）**

A：可能是部分候选模型的 Gateway 维度（G1）失败，导致该模型所有其他维度的 Auto Eval 分值为空。这是正常现象，系统会在数据质量统计里体现 `missing_auto_cells` 数量。
