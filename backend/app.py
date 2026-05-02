"""
中亚新闻地图 - 后端服务
功能：定时抓取 GDELT + RSS 新闻，调用 Gemini 翻译并抽取地点，提供 API
"""
import os
import json
import sqlite3
import hashlib
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import feedparser
from google import genai
from google.genai import types as genai_types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "./news.db")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
USE_MOCK = os.environ.get("USE_MOCK", "false").lower() == "true"

if not GEMINI_API_KEY and not USE_MOCK:
    log.warning("GEMINI_API_KEY 未设置，将以 USE_MOCK 模式启动")
    USE_MOCK = True

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

RSS_FEEDS = [
    {"url": "https://tengrinews.kz/rss/", "country": "KZ", "source": "Tengrinews"},
    {"url": "https://www.kursiv.media/feed/", "country": "KZ", "source": "Kursiv"},
    {"url": "https://www.gazeta.uz/ru/rss/", "country": "UZ", "source": "Gazeta.uz"},
    {"url": "https://kun.uz/ru/rss", "country": "UZ", "source": "Kun.uz"},
    {"url": "https://24.kg/rss/", "country": "KG", "source": "24.kg"},
    {"url": "https://kaktus.media/rss", "country": "KG", "source": "Kaktus.media"},
    {"url": "https://asiaplus.news/ru/feed/", "country": "TJ", "source": "Asia-Plus"},
]

# 每次抓取最多调用 LLM 处理多少条（避免免费额度耗尽）
MAX_LLM_PER_RUN = int(os.environ.get("MAX_LLM_PER_RUN", "20"))
# 每次 LLM 调用之间的间隔秒数（Gemini 免费版每分钟限制 15 次）
LLM_DELAY_SEC = float(os.environ.get("LLM_DELAY_SEC", "4.5"))

CENTRAL_ASIA_BOUNDS = {"lat_min": 35, "lat_max": 56, "lng_min": 46, "lng_max": 87}

MOCK_NEWS = [
    {
        "url": "https://example.com/mock1",
        "title": "Uzbekistan signs energy deal with China",
        "summary": "Tashkent — Uzbekistan and China have signed a major energy cooperation agreement worth $5 billion covering solar, wind and nuclear power.",
        "source": "MockSource",
        "country_hint": "UZ",
        "published": "2026-04-30T08:00:00Z",
        "_mock_result": {
            "title_zh": "乌兹别克斯坦与中国签署 50 亿美元能源合作协议",
            "summary_zh": "塔什干 — 乌兹别克斯坦与中国签署一项重大能源合作协议，总额达 50 亿美元，涵盖太阳能、风能和核能领域。",
            "country": "UZ", "city": "塔什干", "lat": 41.2995, "lng": 69.2401,
            "confidence": 0.95, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock2",
        "title": "Kazakhstan announces new economic reforms",
        "summary": "Astana — President Tokayev announced sweeping reforms in tax system, state-owned enterprises and digital economy.",
        "source": "MockSource",
        "country_hint": "KZ",
        "published": "2026-04-30T06:30:00Z",
        "_mock_result": {
            "title_zh": "哈萨克斯坦总统宣布新一轮经济改革方案",
            "summary_zh": "阿斯塔纳 — 托卡耶夫总统宣布涵盖税制、国企改革和数字经济的大规模改革方案。",
            "country": "KZ", "city": "阿斯塔纳", "lat": 51.1605, "lng": 71.4704,
            "confidence": 0.93, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock3",
        "title": "Almaty hosts first Central Asia tech summit",
        "summary": "Almaty — Over 300 tech companies from five Central Asian countries gathered for the inaugural innovation summit.",
        "source": "MockSource",
        "country_hint": "KZ",
        "published": "2026-04-30T04:15:00Z",
        "_mock_result": {
            "title_zh": "阿拉木图举办首届中亚科技创新峰会",
            "summary_zh": "阿拉木图 — 来自中亚五国的 300 余家科技企业齐聚该市，参加首届科技创新峰会。",
            "country": "KZ", "city": "阿拉木图", "lat": 43.2389, "lng": 76.8897,
            "confidence": 0.92, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock4",
        "title": "Bishkek airport expansion begins",
        "summary": "Bishkek — Construction of the second phase of Manas International Airport has officially begun.",
        "source": "MockSource",
        "country_hint": "KG",
        "published": "2026-04-30T02:00:00Z",
        "_mock_result": {
            "title_zh": "比什凯克新国际机场二期工程动工",
            "summary_zh": "比什凯克 — 玛纳斯国际机场二期扩建工程正式动工，建成后年吞吐量将达 800 万人次。",
            "country": "KG", "city": "比什凯克", "lat": 42.8746, "lng": 74.5698,
            "confidence": 0.90, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock5",
        "title": "Tajikistan Rogun dam fully online",
        "summary": "Dushanbe — All six turbines of the Rogun hydroelectric station are now connected to the grid.",
        "source": "MockSource",
        "country_hint": "TJ",
        "published": "2026-04-29T22:00:00Z",
        "_mock_result": {
            "title_zh": "塔吉克斯坦罗贡水电站全部机组并网",
            "summary_zh": "杜尚别 — 罗贡水电站全部 6 台机组成功并网，年发电量达 170 亿度。",
            "country": "TJ", "city": "杜尚别", "lat": 38.5598, "lng": 68.7870,
            "confidence": 0.94, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock6",
        "title": "Turkmenistan natural gas deal with Iran",
        "summary": "Ashgabat — A 25-year natural gas export agreement signed with Iran for 10 billion cubic meters annually.",
        "source": "MockSource",
        "country_hint": "TM",
        "published": "2026-04-29T20:30:00Z",
        "_mock_result": {
            "title_zh": "土库曼斯坦与伊朗签署天然气出口长期协议",
            "summary_zh": "阿什哈巴德 — 与伊朗签订 25 年期天然气出口协议，年供气量 100 亿立方米。",
            "country": "TM", "city": "阿什哈巴德", "lat": 37.9601, "lng": 58.3261,
            "confidence": 0.91, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock7",
        "title": "Samarkand restoration honored by UNESCO",
        "summary": "Samarkand — Five-year restoration of Timurid-era monuments completed and recognized by UNESCO.",
        "source": "MockSource",
        "country_hint": "UZ",
        "published": "2026-04-29T18:00:00Z",
        "_mock_result": {
            "title_zh": "撒马尔罕古城修复工程获联合国教科文组织表彰",
            "summary_zh": "撒马尔罕 — 历时五年的帖木儿王朝古迹修复工程完工，并获联合国教科文组织认可。",
            "country": "UZ", "city": "撒马尔罕", "lat": 39.6542, "lng": 66.9597,
            "confidence": 0.93, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock8",
        "title": "SCO foreign ministers meet in Astana",
        "summary": "Astana hosts SCO foreign ministers discussing regional security and economic cooperation.",
        "source": "MockSource",
        "country_hint": "KZ",
        "published": "2026-04-29T15:00:00Z",
        "_mock_result": {
            "title_zh": "阿斯塔纳举办上合组织外长会议",
            "summary_zh": "阿斯塔纳 — 上合组织成员国外长围绕地区安全、经济合作展开讨论。",
            "country": "KZ", "city": "阿斯塔纳", "lat": 51.1605, "lng": 71.4704,
            "confidence": 0.92, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock9",
        "title": "New Osh-Kashgar trade corridor opens",
        "summary": "Osh — A new logistics corridor connecting Osh in southern Kyrgyzstan to Kashgar, China has been launched.",
        "source": "MockSource",
        "country_hint": "KG",
        "published": "2026-04-29T12:00:00Z",
        "_mock_result": {
            "title_zh": "吉尔吉斯斯坦南部奥什州开通新跨境物流通道",
            "summary_zh": "奥什 — 连接吉南部奥什与中国喀什的新物流通道开通，物流时效缩短 40%。",
            "country": "KG", "city": "奥什", "lat": 40.5283, "lng": 72.7985,
            "confidence": 0.90, "lang_orig": "en"
        }
    },
    {
        "url": "https://example.com/mock10",
        "title": "Tashkent metro new line opens",
        "summary": "Tashkent — A 19-kilometer new metro line with 11 stations has officially opened.",
        "source": "MockSource",
        "country_hint": "UZ",
        "published": "2026-04-29T10:00:00Z",
        "_mock_result": {
            "title_zh": "塔什干地铁新线路正式通车",
            "summary_zh": "塔什干 — 19 公里长的新地铁线路通车，设 11 座车站，预计日均客流 25 万。",
            "country": "UZ", "city": "塔什干", "lat": 41.3110, "lng": 69.2790,
            "confidence": 0.91, "lang_orig": "en"
        }
    },
]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id TEXT PRIMARY KEY,
            source_url TEXT UNIQUE NOT NULL,
            source_name TEXT,
            country TEXT,
            city TEXT,
            lat REAL,
            lng REAL,
            title_orig TEXT,
            title_zh TEXT,
            summary_orig TEXT,
            summary_zh TEXT,
            published_at TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
            confidence REAL,
            lang_orig TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_published ON news(published_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON news(country)")
    conn.commit()
    conn.close()
    log.info(f"数据库初始化完成: {DB_PATH}")


def url_to_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


async def fetch_rss(feed_info: dict) -> list:
    items = []
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                feed_info["url"],
                headers={"User-Agent": "Mozilla/5.0 (compatible; CentralAsiaNewsMap/1.0)"}
            )
            parsed = feedparser.parse(resp.text)
            for entry in parsed.entries[:30]:
                items.append({
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "summary": (entry.get("summary", "") or "")[:1500],
                    "source": feed_info["source"],
                    "country_hint": feed_info["country"],
                    "published": entry.get("published", "") or entry.get("updated", "")
                })
        log.info(f"RSS {feed_info['source']}: 拿到 {len(items)} 条")
    except Exception as e:
        log.error(f"RSS {feed_info['source']} 失败: {e}")
    return items


async def fetch_gdelt() -> list:
    items = []
    countries = ["KZ", "UZ", "KG", "TJ", "TM"]
    for cc in countries:
        try:
            url = (
                f"https://api.gdeltproject.org/api/v2/doc/doc"
                f"?query=sourcecountry:{cc}&mode=ArtList&maxrecords=20"
                f"&format=json&sort=DateDesc"
            )
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url)
                data = resp.json()
                for art in data.get("articles", []):
                    items.append({
                        "url": art.get("url", ""),
                        "title": art.get("title", ""),
                        "summary": art.get("title", ""),
                        "source": art.get("domain", "GDELT"),
                        "country_hint": cc,
                        "published": art.get("seendate", "")
                    })
            log.info(f"GDELT {cc}: 拿到数据")
        except Exception as e:
            log.error(f"GDELT {cc} 失败: {e}")
    return items


def already_have(url: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM news WHERE source_url = ?", (url,)).fetchone()
    conn.close()
    return row is not None


def llm_process(item: dict):
    """调用 Gemini：翻译 + 抽地点。USE_MOCK 模式直接返回内置结果。"""
    if USE_MOCK:
        return item.get("_mock_result")

    prompt = f"""你是新闻分析助手。给定一条新闻的原文标题和摘要，请：
1. 把标题和摘要翻译成简洁的中文
2. 识别新闻"主要发生地"的城市和国家（必须是中亚五国：哈萨克斯坦KZ/乌兹别克斯坦UZ/吉尔吉斯斯坦KG/塔吉克斯坦TJ/土库曼斯坦TM）
3. 给出该城市的经纬度（标准 WGS84）
4. 评估你的判断置信度 0-1

新闻原文：
标题：{item['title']}
摘要：{item['summary']}
来源国提示：{item.get('country_hint') or '未知'}

只返回 JSON，不要其他文字：
{{
  "title_zh": "中文标题",
  "summary_zh": "中文摘要 100-200 字",
  "country": "KZ/UZ/KG/TJ/TM 之一，如果不属于中亚返回 null",
  "city": "城市中文名",
  "lat": 41.31,
  "lng": 69.24,
  "confidence": 0.85,
  "lang_orig": "原文语种代码 ru/en/uz/kk 等"
}}"""
    try:
        resp = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=2048,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            log.error(f"LLM 返回空文本: finish={resp.candidates[0].finish_reason if resp.candidates else 'N/A'}")
            return None
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as je:
            log.error(f"LLM JSON 解析失败: {je}; 原文前 200 字: {text[:200]!r}")
            return None
        if not data.get("country") or data["country"] not in ["KZ", "UZ", "KG", "TJ", "TM"]:
            return None
        if data.get("confidence", 0) < 0.5:
            return None
        b = CENTRAL_ASIA_BOUNDS
        if not (b["lat_min"] <= data["lat"] <= b["lat_max"] and b["lng_min"] <= data["lng"] <= b["lng_max"]):
            return None
        return data
    except Exception as e:
        log.error(f"LLM 处理失败: {e}")
        return None


def save_news(item: dict, llm_result: dict):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO news
            (id, source_url, source_name, country, city, lat, lng,
             title_orig, title_zh, summary_orig, summary_zh,
             published_at, confidence, lang_orig)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            url_to_id(item["url"]),
            item["url"],
            item["source"],
            llm_result["country"],
            llm_result["city"],
            llm_result["lat"],
            llm_result["lng"],
            item["title"],
            llm_result["title_zh"],
            item["summary"],
            llm_result["summary_zh"],
            item["published"],
            llm_result["confidence"],
            llm_result.get("lang_orig", "")
        ))
        conn.commit()
    finally:
        conn.close()


async def run_ingest():
    log.info("=== 开始抓取 ===")
    if USE_MOCK:
        log.info("MOCK 模式：使用内置模拟数据")
        all_items = MOCK_NEWS
    else:
        all_items = []
        for feed in RSS_FEEDS:
            all_items.extend(await fetch_rss(feed))
        all_items.extend(await fetch_gdelt())

    log.info(f"原始抓取 {len(all_items)} 条")

    seen_urls = set()
    new_items = []
    skipped_existing = 0
    for it in all_items:
        if not it["url"] or it["url"] in seen_urls:
            continue
        if already_have(it["url"]):
            skipped_existing += 1
            seen_urls.add(it["url"])
            continue
        seen_urls.add(it["url"])
        new_items.append(it)

    log.info(f"去重后 {len(new_items)} 条新条目（{skipped_existing} 条已存在）")

    if USE_MOCK:
        limit = len(new_items)
    else:
        limit = MAX_LLM_PER_RUN
    items_to_process = new_items[:limit]
    if len(new_items) > limit:
        log.info(f"本轮只处理前 {limit} 条（避免 LLM 限额）")

    processed = 0
    rejected = 0
    for idx, it in enumerate(items_to_process, 1):
        result = llm_process(it)
        if result:
            save_news(it, result)
            processed += 1
            log.info(f"[{idx}/{len(items_to_process)}] ✓ 入库: {result['city']} - {result['title_zh'][:40]}")
        else:
            rejected += 1
            log.info(f"[{idx}/{len(items_to_process)}] ✗ 丢弃: {it['title'][:60]}")
        if not USE_MOCK and idx < len(items_to_process):
            await asyncio.sleep(LLM_DELAY_SEC)

    log.info(f"=== 抓取完成：新增 {processed} 条，丢弃 {rejected} 条 ===")
    return processed


def cleanup_old():
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM news WHERE fetched_at < ?", (cutoff,))
    conn.commit()
    conn.close()
    log.info("清理 30 天前数据完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_ingest, "interval", minutes=30, next_run_time=datetime.now())
    scheduler.add_job(cleanup_old, "cron", hour=3)
    scheduler.start()
    log.info(f"调度器启动 (mock={USE_MOCK})")
    yield
    scheduler.shutdown()


app = FastAPI(title="中亚新闻地图 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "中亚新闻地图 API",
        "version": "0.1.0",
        "endpoints": ["/api/news", "/api/health", "/api/refresh"]
    }


@app.get("/api/news")
def get_news(days: int = 7, country: str | None = None, limit: int = 500):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM news WHERE (published_at > ? OR fetched_at > ?)"
    params = [cutoff, cutoff]
    if country and country != "ALL":
        sql += " AND country = ?"
        params.append(country)
    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    items = [dict(row) for row in rows]
    return {"count": len(items), "items": items}


@app.get("/api/health")
def health():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    last = conn.execute("SELECT MAX(fetched_at) FROM news").fetchone()[0]
    conn.close()
    return {
        "status": "ok",
        "mode": "mock" if USE_MOCK else "live",
        "total_news": total,
        "last_fetched": last
    }


@app.post("/api/refresh")
async def refresh():
    """手动触发一次抓取"""
    try:
        added = await run_ingest()
        return {"status": "ok", "added": added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
