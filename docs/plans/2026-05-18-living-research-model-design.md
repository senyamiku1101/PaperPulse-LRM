# PaperPulse 重构设计：活的研究前沿模型

**日期**: 2026-05-18
**状态**: 已批准

---

## 1. 背景与动机

### 当前问题

当前 PaperPulse 采用"种子 DOI → 展开引用/被引 → 全量 AI 分析"的流程。以 300 篇种子论文为例，仅参考文献就会产生 5000+ 篇候选，导致：

- 大量不相关论文涌入（引用边被等价对待）
- AI 分析成本不可控
- 扁平列表无法体现研究结构
- 前沿追踪能力弱（引用展开偏向历史文献）

### 核心范式转换

> 从"论文追踪器"到"研究前沿的活模型"

- **旧范式**: 种子 → 引用展开 → 论文列表 → AI 总结每篇
- **新范式**: 研究问题 → 结构化主张 → 证据论文 → 差距/趋势/矛盾

系统的输出不是"本周发现 N 篇新论文"，而是"本周你的前沿模型在这 3 个地方发生了变化"。

---

## 2. 数据模型

### 2.1 `questions.json` — 研究问题图谱

```json
{
  "questions": [
    {
      "id": "q_broadband_distortion",
      "name": "进气畸变下的宽频噪声机理",
      "description": "非均匀来流条件下风扇宽频噪声的产生机制与预测方法",
      "seed_dois": ["10.1115/1.4051782"],
      "keywords": ["broadband noise", "distortion", "inlet flow"],
      "methods_of_interest": ["LES", "DES", "experiment"],
      "status": "active",
      "last_updated": "2026-05-18",
      "evidence_count": 12,
      "gap_flags": ["缺乏实验验证"]
    }
  ]
}
```

初始问题由 AI 从种子 DOI 的标题/摘要自动聚类生成，用户可编辑。

### 2.2 `claims.json` — 结构化主张库

```json
{
  "claims": [
    {
      "id": "claim_001",
      "question_id": "q_broadband_distortion",
      "statement": "锯齿尾缘在均匀来流下可降低宽频噪声 3-5dB",
      "method": "LES + FW-H",
      "evidence_type": "numerical",
      "geometry": "axial fan",
      "condition": "uniform inflow, low Mach",
      "outcome": "3-5dB SPL reduction at 1-4kHz",
      "limitation": "未在畸变来流下验证",
      "supporting_papers": ["W123", "W456"],
      "contradicting_papers": [],
      "confidence": "moderate",
      "created_at": "2026-05-18"
    }
  ]
}
```

### 2.3 `papers.json` — 论文（精简版）

```json
{
  "id": "W...",
  "doi": "...",
  "title": "...",
  "year": 2025,
  "abstract": "...",
  "authors": [],
  "topics": [],
  "source": {},
  "role": "seed | promoted | candidate",
  "question_ids": ["q_broadband_distortion"],
  "claim_ids": ["claim_001"],
  "discovery_reason": "cites 3 seeds in q_broadband_distortion",
  "scores": { "total": 7.8, "components": {} },
  "analysis": null
}
```

### 2.4 `frontier.json` — 每周前沿变化

```json
{
  "week": "2026-W20",
  "generated_at": "2026-05-18",
  "changes": [
    {
      "type": "new_evidence",
      "question_id": "q_broadband_distortion",
      "summary": "2篇新论文支持锯齿尾缘降噪主张",
      "paper_ids": ["W789", "W012"]
    },
    {
      "type": "emerging_method",
      "description": "3个课题组开始使用 PINN 方法预测风扇噪声",
      "paper_ids": ["W111", "W222", "W333"]
    },
    {
      "type": "gap_persisting",
      "question_id": "q_tip_clearance",
      "description": "叶尖间隙噪声仍缺乏大尺度实验数据"
    }
  ],
  "top_papers": [],
  "model_diff_summary": "本周模型变化：3个问题有新证据，1个新兴方法出现"
}
```

### 2.5 `candidates.json` — 候选池（内部使用）

```json
{
  "candidates": [
    {
      "id": "W...",
      "doi": "...",
      "title": "...",
      "abstract": "...",
      "year": 2025,
      "discovered_via": "citing_seed",
      "seed_connections": ["W_seed_1", "W_seed_3"],
      "question_scores": {
        "q_broadband_distortion": 6.5,
        "q_tip_clearance": 1.2
      },
      "best_question": "q_broadband_distortion",
      "promoted": false,
      "reason": "title/abstract 匹配度不足"
    }
  ]
}
```

### 2.6 `seed_dois.json` — 格式升级

```json
[
  {
    "doi": "10.1115/1.4051782",
    "zotero_collections": ["宽频噪声", "叶尖间隙"],
    "synced_at": "2026-05-18"
  }
]
```

---

## 3. Zotero 集成

### 3.1 方案：Zotero Web API + 多集合监听

用户在 Zotero 中按研究主题组织集合，PaperPulse 通过 Zotero Web API 定期同步所有指定集合作为统一种子池。

### 3.2 配置

```python
# config.py
ZOTERO_USER_ID = os.getenv("ZOTERO_USER_ID", "")
ZOTERO_API_KEY = os.getenv("ZOTERO_API_KEY", "")
ZOTERO_COLLECTIONS = os.getenv("ZOTERO_COLLECTIONS", "")
# 格式: "集合名1,集合名2" 或留空表示全部
```

### 3.3 阶段 0：种子同步流程

1. 调用 Zotero Web API 获取指定集合中的所有条目
2. 提取 DOI，记录来源集合
3. 与 `seed_dois.json` 比对，追加新增
4. 输出更新后的种子列表

### 3.4 增量更新策略

- 新增种子 < 5 篇：自动归入最匹配的现有问题
- 新增种子 ≥ 5 篇：触发增量聚类
- 用户可手动触发完全重新聚类

---

## 4. 每周更新流水线

### 4.1 阶段总览

```
阶段0: Zotero 种子同步 (0次AI, 1-2次Zotero API)
阶段1: 初始化问题图谱 (仅首次/手动, 1次AI)
阶段2: 候选发现 (每周, 0次AI, ~30次OpenAlex)
阶段3: 廉价评分与筛选 (每周, 0次AI, 纯Python)
阶段4: 结构化主张提取 (每周, ≤30次AI)
阶段5: 问题状态更新 (每周, ≤8次AI)
阶段6: 前沿差异生成 (每周, 1次AI)
阶段7: 前端数据导出 (每周, 0次AI)
```

### 4.2 AI 调用预算

| 阶段 | OpenAlex | DeepSeek |
|------|----------|----------|
| 阶段2: 候选发现 | ~30 | 0 |
| 阶段3: 廉价评分 | 0 | 0 |
| 阶段4: 主张提取 | 0 | ≤30 |
| 阶段5: 问题状态 | 0 | ≤8 |
| 阶段6: 前沿差异 | 0 | 1 |
| **总计** | **~30** | **≤39** |

### 4.3 阶段 1：初始化问题图谱

- 输入：种子 DOI 列表 + Zotero 集合信息
- 流程：批量获取标题/摘要 → DeepSeek 聚类为 6-12 个研究问题
- 输出：`questions.json`
- AI 调用：1 次

### 4.4 阶段 2：候选发现

三条并行路径，全部走 OpenAlex API：

- **路径 A — 引用者追踪**：每个种子的最新引用者，最近 1 年，每种子最多 50 篇
- **路径 B — 关键词搜索**：每个问题的关键词组合搜索，最近 6 个月
- **路径 C — 关注列表**：已标记的作者/课题组/期刊的新论文

输出：新增候选写入 `candidates.json`

### 4.5 阶段 3：廉价评分

纯 Python 计算，无 API 调用：

```
score = keyword_overlap (0-3)
      + topic_match (0-2)
      + seed_connections (0-3)
      + multi_seed_bonus (+2)
      + recency_bonus (0-1)
      + venue_match (0-1)
      - negative_keywords (-2)
```

阈值 ≥5 分的候选被提升为 promoted。每个问题最多 5 篇/周，全局上限 30 篇/周。

### 4.6 阶段 4：结构化主张提取

- 输入：promoted 论文中 `analysis=None` 的
- 流程：调用 DeepSeek 提取结构化主张（替代传统摘要）
- 输出：填充 `papers.json` 的 `analysis`，新增 `claims.json` 条目

### 4.7 阶段 5：问题状态更新

- 输入：本周新增主张 + 现有问题
- 流程：对有新证据的问题调用 DeepSeek 更新状态
- 输出：更新 `questions.json`

### 4.8 阶段 6：前沿差异生成

- 输入：本周所有变化
- 流程：调用 DeepSeek 生成周报
- 输出：`frontier.json`

---

## 5. 前端 UI

### 5.1 页面结构

```
首页 → 研究问题仪表盘 | 前沿周报 | 待读队列 | 研究机会 | 论文库 | 趋势 | 课题组 | AI问答
```

### 5.2 研究问题仪表盘（新首页）

卡片式布局，每个研究问题一张卡片，显示：
- 问题名称 + 状态标签
- 证据论文数量 + 本周变化
- 最新主张
- 研究差距提示

### 5.3 前沿周报

显示本周模型变化：最重要的发现、新兴趋势、持续差距、推荐阅读。

### 5.4 待读队列

系统推荐的论文，按优先级排序，显示推荐理由。

### 5.5 研究机会地图

多维矩阵（方法 × 验证类型、噪声机制 × 几何构型等），可视化稀疏/空白区域。

### 5.6 论文库

保留现有功能，增加按问题筛选、显示推荐理由。

### 5.7 趋势/课题组/AI问答

适配新数据模型，可按问题分层显示。

---

## 6. 分阶段实施

### Phase 0：基础设施（1-2天）

- Zotero Web API 集成 (`scripts/zotero_client.py`)
- 种子同步逻辑 (`scripts/sync_seeds.py`)
- 数据模型扩展 (`candidates.json`, `questions.json` 等)
- `seed_dois.json` 格式升级

### Phase 1：廉价筛选漏斗（2-3天）

- 候选发现重写 (`scripts/fetch_papers.py`)
- 廉价评分逻辑 (`scripts/scoring.py`)
- 候选提升逻辑 (`scripts/promote.py`)
- AI 分析仅作用于 promoted 论文

### Phase 2：问题图谱 + 主张提取（3-4天）

- 问题聚类初始化 (`scripts/init_questions.py`)
- 结构化主张提取 (`scripts/extract_claims.py`)
- 问题状态更新 (`scripts/update_questions.py`)
- 前沿差异生成 (`scripts/generate_frontier.py`)

### Phase 3：前端重构（3-4天）

- 问题仪表盘
- 前沿周报页
- 待读队列
- 研究机会地图
- 论文库适配新数据模型

---

## 7. 现有数据迁移

| 现有数据 | 迁移方式 |
|----------|----------|
| `papers.json` (28篇) | 保留，DOI 在 seed_dois.json 中的标记为 `seed`，其余标记为 `promoted` |
| `seed_dois.json` (150 DOI) | 格式升级，补充 `zotero_collections` 字段 |
| `trends.json` | 保留，Phase 3 中适配新数据源 |
| `summary.json` | 保留，Phase 3 中适配 |
| `groups.json` | 保留，Phase 3 中适配 |
| DeepSeek 分析结果 | 保留，新论文用新格式的 claims |

---

## 8. 关键设计决策

1. **候选池与论文库分离**：`candidates.json` 是内部工作区，`papers.json` 只包含已提升的论文
2. **廉价评分优先于 AI**：纯 Python 评分筛选后，AI 只处理 top 候选
3. **Zotero 集合信息作为聚类提示**：不直接决定问题归属，但为 AI 聚类提供高质量输入
4. **增量更新优于全量重建**：种子变化 <5 篇时自动归入现有问题，避免频繁重聚类
5. **问题状态驱动更新**：只有有新证据的问题才触发 AI 更新，节省调用
