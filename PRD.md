# 中亚新闻地图 — 产品需求文档（MVP）

**版本**：v0.1 (MVP)
**最后更新**：2026-04-30
**作者**：Lee Qi

---

## 1. 产品概述

### 1.1 一句话定位
一个把中亚五国（哈萨克斯坦、乌兹别克斯坦、吉尔吉斯斯坦、塔吉克斯坦、土库曼斯坦）的新闻按发生地点呈现在地图上的中文新闻聚合网站。

### 1.2 核心价值
- **空间维度阅读新闻**：按"哪里发生了什么"探索资讯，而非按时间或媒体源
- **聚焦中亚**：填补中文互联网对中亚报道的空白
- **零语言门槛**：所有内容自动翻译为中文

### 1.3 产品形态
纯网页应用，桌面端优先，无需注册。MVP 阶段所有服务部署在境外，用户访问需 VPN（自用为主）。

---

## 2. 用户场景

### 2.1 目标用户
- 关注中亚地缘政治、经济、社会的中文读者
- 中亚相关从业者：贸易、研究、媒体、留学生
- 一带一路相关行业人员

### 2.2 典型场景

**A. 今日扫读**：打开网站 → 看到地图上中亚区域的新闻点 → 点击塔什干 → 看到"乌兹别克与中国签署能源协议"标题摘要 → 查看原文。

**B. 地区聚焦**：缩放地图到比什凯克 → 浏览周边所有点位。

**C. 随机发现**：点击不熟悉的城市 → 通过新闻了解该地区。

---

## 3. MVP 功能清单

### 3.1 必做

| 功能 | 说明 |
|---|---|
| 中亚地图 | 默认覆盖五国，可缩放/平移 |
| 新闻点位 | 圆点标记，按国家配色 |
| 点击弹窗 | 标题、摘要、来源、时间、原文链接 |
| 中文翻译 | 标题摘要自动翻译 |
| 国家筛选 | 顶部 chips：全部/KZ/UZ/KG/TJ/TM |
| 列表-地图联动 | 列表 hover/点击高亮地图点位 |
| 自动抓取 | 后端每 30 分钟拉新闻 |
| 数据保鲜 | 默认显示最近 7 天 |

### 3.2 不做（V2 再考虑）

- 用户登录、收藏、订阅
- 关键词搜索
- 时间筛选 / 时间轴回放
- 主题分类筛选
- 移动端适配
- 全文翻译
- 评论 / 分享

### 3.3 边界

- **只做中亚五国**：不扩展
- **只做中文界面**
- **不存原文**：避免版权风险，只存标题、摘要、链接

---

## 4. 技术架构

### 4.1 部署模式

```
Vercel（前端）→ Vultr 东京（后端 + DB）→ GDELT/RSS + Claude API
                ↑
              用户（开 VPN 访问）
```

### 4.2 技术栈

| 层 | 选型 |
|---|---|
| 后端语言 | Python 3.11 |
| Web 框架 | FastAPI |
| 数据库 | SQLite（MVP），后续可迁移 PostgreSQL |
| 任务调度 | APScheduler |
| LLM | Claude Haiku 4.5 |
| 前端 | 原生 HTML/JS |
| 地图 | 高德地图 JS API 2.0 |
| 前端托管 | Vercel |
| 后端托管 | Vultr Cloud Compute（东京） |
| 反向代理 | Caddy（HTTPS 自动证书） |

### 4.3 数据源

**主源 GDELT**：覆盖五国，每 30 分钟拉一次，每国最近 20 条。

**RSS 辅源**：
- KZ：Tengrinews
- UZ：Gazeta.uz
- KG：24.kg
- TJ：Asia-Plus
- 区域：Eurasianet

土库曼斯坦信息封闭，靠 GDELT 兜底。

---

## 5. 核心数据流

```
[每 30 分钟触发]
  ↓
拉 GDELT + RSS（每源最近 20-30 条）
  ↓
URL 去重 + 数据库已有去重
  ↓
逐条调 Claude Haiku：
  输入：原文标题 + 摘要 + 国家提示
  输出：JSON {title_zh, summary_zh, country, city, lat, lng, confidence, lang_orig}
  ↓
过滤：country 不在 KZ/UZ/KG/TJ/TM 丢弃
过滤：confidence < 0.5 丢弃
过滤：坐标不在中亚 bbox 丢弃
  ↓
INSERT OR IGNORE 入库
```

---

## 6. 接口设计

### 6.1 GET `/api/news`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| days | int | 7 | 最近 N 天 |
| country | string | 无 | KZ/UZ/KG/TJ/TM |
| limit | int | 500 | 最多条数 |

返回：
```json
{
  "count": 234,
  "items": [
    {
      "id": "a1b2c3",
      "title_zh": "...",
      "summary_zh": "...",
      "source_name": "Gazeta.uz",
      "source_url": "https://...",
      "country": "UZ",
      "city": "塔什干",
      "lat": 41.2995,
      "lng": 69.2401,
      "published_at": "2026-04-30T08:00:00Z",
      "confidence": 0.92
    }
  ]
}
```

### 6.2 GET `/api/health`

```json
{ "status": "ok", "total_news": 234, "last_fetched": "2026-04-30T08:30:00Z" }
```

---

## 7. 数据库结构

```sql
CREATE TABLE news (
    id TEXT PRIMARY KEY,           -- url sha1 前 12 位
    source_url TEXT UNIQUE NOT NULL,
    source_name TEXT,
    country TEXT,                  -- KZ/UZ/KG/TJ/TM
    city TEXT,
    lat REAL,
    lng REAL,
    title_orig TEXT,
    title_zh TEXT,
    summary_orig TEXT,
    summary_zh TEXT,
    published_at TEXT,
    fetched_at TEXT,
    confidence REAL,
    lang_orig TEXT
);
CREATE INDEX idx_published ON news(published_at);
CREATE INDEX idx_country ON news(country);
```

清理策略：每天凌晨 3 点删 30 天前数据。

---

## 8. 视觉与交互

详见：
- [`设计规范.md`](./设计规范.md) — 配色、字体、组件样式
- [`页面结构.md`](./页面结构.md) — 线框图、状态、流程
- [`prototype.html`](./prototype.html) — 可运行原型

要点：
- 深色风格 + 中亚地域色（突厥蓝 / 沙色）
- 地图 70% + 列表 30%（≥ 1280px）
- 国家用色区分点位

---

## 9. 风险与应对

| 风险 | 影响 | 缓解 |
|---|---|---|
| GDELT 中亚覆盖密度一般 | 新闻数量少 | 加 RSS 辅源 |
| LLM 抽地点错误 | 点位错位 | confidence < 0.5 丢弃 + 中亚 bbox 校验 |
| 翻译成本超预期 | 月成本 > $20 | UptimeRobot 监控 + 手动巡检 |
| 版权 | 法律风险 | 只展示标题摘要 + 原文链接，不抓全文 |
| Vultr 余额耗尽 | 服务器被删 | 自动扣款 / 月度巡检 |
| Claude API key 失效 | 抓取停滞 | 监控 health 接口 + 告警 |

---

## 10. 成本预估

| 项目 | 月费 |
|---|---|
| Vultr Cloud Compute | $6 |
| Claude Haiku（约 500 条/天） | $5-15 |
| 高德 JS API | 免费（30k 次/天额度内） |
| Vercel Hobby | 免费 |
| 域名（可选） | ~$1 |
| **合计** | **约 $12-22** |

---

## 11. 上线里程碑

| 阶段 | 时间 | 完成标志 |
|---|---|---|
| 准备 | 2-3 小时 | SSH 能连服务器，所有 key 拿齐 |
| 后端 | 1-2 天 | `/api/news` 返回真实数据 |
| 前端 | 2 小时 | Vercel 域名能访问，地图有点位 |
| 联调 | 半天 | 24 小时无人值守自动更新 |

详见 [`00_执行总览.md`](./00_执行总览.md)。

---

## 12. 成功指标

- 每日新增新闻 ≥ 50 条
- 地点定位准确率 ≥ 80%（人工抽检 50 条）
- 翻译可读性 ≥ 90%（无明显错译）
- 页面首次加载 ≤ 3 秒
- 7×24 稳定运行，月度宕机 < 1 小时

---

## 13. V2 路线图

按优先级：

1. 关键词搜索
2. 时间轴回放
3. 主题分类（政治 / 经济 / 社会 / 文化）
4. 移动端适配
5. 邮件 / RSS 订阅
6. 扩展区域（高加索、蒙古、阿富汗）
7. 数据可视化（热力图、统计面板）
8. 按需全文翻译 + 缓存

---

**文档结束**
