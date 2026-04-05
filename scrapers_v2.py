#!/usr/bin/env python3
"""
scrapers_v2.py — GCC Think Tank Content Scraper（修复版）
==========================================================
抓取三个智库官网中与GCC相关的研究内容：

1. Brookings CMEP  — 用 /regions/middle-east-north-africa/gulf-states/ 等子页
                     + 补充关键词（Hormuz / Red Sea / strait 等间接词）
2. AJCS            — studies.aljazeera.net，Drupal站，<h4><a> 结构
                     + 放宽关键词，加 gulf / hormuz / red sea 等
3. Rasanah         — rasanah-iiis.org，WordPress站，<h2><a> 结构
                     + 修复href拼接逻辑，放宽过滤（内容几乎全是海湾相关）

用法:
    python scrapers_v2.py --all --test    # 测试（每源少量抓取）
    python scrapers_v2.py --all           # 正式运行
    python scrapers_v2.py --source ajcs   # 只跑单个
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import re
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, asdict, field
from typing import Optional

# ──────────────────────────────────────────────
# 日志
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scrapers.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("scrapers_v2")


# ──────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────
@dataclass
class Article:
    source_id: str
    source_name: str
    title: str
    url: str
    date: Optional[str] = None
    content_type: Optional[str] = None
    authors: list = field(default_factory=list)
    gcc_keywords: list = field(default_factory=list)
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# GCC 关键词（扩充版，加入间接相关词）
# ──────────────────────────────────────────────
GCC_KEYWORDS = [
    # 直接词
    "gcc", "gulf cooperation council",
    "saudi arabia", "united arab emirates", "uae",
    "bahrain", "oman", "kuwait", "qatar",
    # 地理/通称
    "gulf states", "gulf state", "arabian gulf", "persian gulf",
    "gulf security", "gulf economy", "gulf region",
    "gulf cooperation", "gulf monarchies", "gulf monarchy",
    # 城市
    "riyadh", "abu dhabi", "dubai", "doha",
    "manama", "muscat", "kuwait city", "jeddah",
    # 战略/经济
    "vision 2030", "neom", "aramco", "sabic",
    "opec", "sovereign wealth", "petrodollar",
    # 地缘（间接相关，Rasanah/AJCS常见）
    "strait of hormuz", "hormuz", "red sea",
    "houthis", "houthi", "yemen", "iran-gulf",
    "iran-saudi", "iran-arab",
]

def match_gcc(text: str) -> list:
    t = text.lower()
    return [kw for kw in GCC_KEYWORDS if kw in t]

def is_gcc_relevant(text: str) -> bool:
    return bool(match_gcc(text))

EXCLUDE_WORDS = [
    "register now", "save the date", "join us for",
    "rsvp", "invitation", "attend the",
]

EXCLUDE_TITLES = [
    "iran in a week",   # Rasanah周报，不是研究文章
]

def is_event(title: str) -> bool:
    t = title.lower()
    if any(w in t for w in EXCLUDE_WORDS):
        return True
    if any(t == excl for excl in EXCLUDE_TITLES):
        return True
    return False


# ──────────────────────────────────────────────
# HTTP 工具
# ──────────────────────────────────────────────
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})
DELAY = 2.0
LOOKBACK_DAYS = 90

def fetch(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=20, allow_redirects=True)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning(f"  [{attempt+1}/{retries}] {e} — retry in {wait}s")
            time.sleep(wait)
    log.error(f"  Failed: {url}")
    return None

def pause():
    time.sleep(DELAY)

def parse_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
                "%Y-%m-%d", "%B %Y", "%b %Y"]:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None

def is_recent(date_str: Optional[str]) -> bool:
    if not date_str:
        return True
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return d >= datetime.now() - timedelta(days=LOOKBACK_DAYS)
    except Exception:
        return True

def extract_date_from_text(text: str) -> Optional[str]:
    """从一段文本里提取日期，支持多种格式"""
    # "March 19, 2026" 或 "19 March 2026" 或 "19 Mar 2026"
    patterns = [
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        r"\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
        r"\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return parse_date(m.group(0))
    return None


# ═══════════════════════════════════════════════════════════════
# 1. BROOKINGS CENTER FOR MIDDLE EAST POLICY
# ═══════════════════════════════════════════════════════════════
#
# 问题根因：Brookings 的 "Research and commentary" 页只静态渲染
#           最新4篇，其余靠 JS 过滤器加载。
#
# 解决方案：
#   A. 用 GCC 国家子页（/gulf-states/ /saudi-arabia/ /bahrain/）
#      这些页面文章数量也少，但都是精准GCC内容，不需要关键词过滤
#   B. 补充直接用 Brookings 全站搜索 API（返回JSON，无需JS）
#      URL: https://www.brookings.edu/wp-json/wp/v2/posts?
#           categories=...&per_page=20&search=gulf+saudi
#
# ═══════════════════════════════════════════════════════════════

# Brookings WordPress REST API — 直接返回JSON，完全绕过JS渲染
# 用 search 参数搜关键词，tag/category 参数过滤地区
# Brookings WordPress API 支持按 region tag 过滤
# 通过在文章URL里找 /regions/middle-east-north-africa/ 来过滤
# API端点: /wp-json/wp/v2/posts 支持 search 参数
BROOKINGS_API_SEARCHES = [
    "Saudi Arabia Gulf",
    "Gulf Cooperation Council",
    "UAE Emirates Gulf",
    "Qatar Doha",
    "Bahrain Kuwait Oman Gulf",
    "Strait of Hormuz",
    "Saudi Vision 2030",
    "Gulf states policy",
]

def scrape_brookings(test_mode: bool = False) -> list[Article]:
    max_items = 10 if test_mode else 60
    articles = []
    seen_urls = set()

    # 方法A：GCC国家子页面（静态抓，不过滤关键词）
    subpages = [
        ("https://www.brookings.edu/regions/middle-east-north-africa/gulf-states/",  "gulf_states"),
        ("https://www.brookings.edu/regions/middle-east-north-africa/saudi-arabia/", "saudi_arabia"),
        ("https://www.brookings.edu/regions/middle-east-north-africa/bahrain/",      "bahrain"),
    ]

    for url, label in subpages:
        log.info(f"Brookings subpage [{label}] → {url}")
        soup = fetch(url)
        if not soup:
            pause()
            continue

        # 找所有指向 /articles/ /reports/ /papers/ 的链接
        for a in soup.find_all("a", href=True):
            href = a["href"]
            title = a.get_text(strip=True)
            # Brookings文章路径：/articles/ /reports/ /papers/ /essay/ 等
            # 也包括直接 /year/month/slug 格式
            if not re.search(r"/(articles|reports|papers|books|essay|brief)/", href):
                # 兜底：匹配 brookings.edu/[年份] 或纯路径文章链接
                if not re.match(r"https://www\.brookings\.edu/\d{4}/", href):
                    if "brookings.edu" not in href:
                        continue
            if len(title) < 15:
                continue
            # 排除导航、footer、作者页、事件页、机构页等非文章链接
            skip_patterns = [
                "/experts/", "/events/", "/programs/", "/topics/", "/regions/",
                "/about", "/careers", "/newsletters", "/donate", "/for-media",
                "/people/", "/centers/", "/dei-", "/contact", "/support",
                "/all-books/", "/podcasts/", "/research-programs/",
                "/research-commentary/", "/tags/", "/collection/",
            ]
            if any(p in href for p in skip_patterns):
                continue
            # 必须有实际标题（排除导航文字如"Research Programs"、"Contact Brookings"）
            if title in ["Research Programs", "Research & Commentary", "Contact Brookings",
                         "Brookings Institution Press", "For Media", "About Us",
                         "Diversity, Equity, and Inclusion"]:
                continue
            full_url = urljoin("https://www.brookings.edu", href)
            if full_url in seen_urls:
                continue
            if is_event(title):
                continue

            # 找日期
            date_str = None
            parent = a.parent
            for _ in range(6):
                if parent is None:
                    break
                date_str = extract_date_from_text(parent.get_text(" "))
                if date_str:
                    break
                parent = parent.parent

            if date_str and not is_recent(date_str):
                continue

            # 子页面内容就是GCC相关，直接收录
            articles.append(Article(
                source_id="brookings_cmep",
                source_name="Brookings Center for Middle East Policy",
                title=title,
                url=full_url,
                date=date_str,
                content_type="article" if "/articles/" in full_url else "report",
                gcc_keywords=match_gcc(title) or [label],
            ))
            seen_urls.add(full_url)

        pause()

    # 方法B：WordPress REST API，搜GCC关键词（获取更多内容）
    log.info("Brookings API search...")
    for search_term in BROOKINGS_API_SEARCHES:
        api_url = (
            f"https://www.brookings.edu/wp-json/wp/v2/posts"
            f"?search={requests.utils.quote(search_term)}"
            f"&per_page=10&orderby=date&order=desc"
            f"&_fields=id,title,link,date,excerpt,type"
        )
        try:
            r = SESSION.get(api_url, timeout=20)
            r.raise_for_status()
            posts = r.json()
            if not isinstance(posts, list):
                continue
            for post in posts:
                title = BeautifulSoup(
                    post.get("title", {}).get("rendered", ""), "lxml"
                ).get_text(strip=True)
                url = post.get("link", "")
                date_raw = post.get("date", "")[:10]
                excerpt_html = post.get("excerpt", {}).get("rendered", "")
                summary = BeautifulSoup(excerpt_html, "lxml").get_text(strip=True)[:200]

                if not title or not url or url in seen_urls:
                    continue
                if is_event(title):
                    continue
                # API已经用GCC关键词搜索，只排除明显不相关的结果
                # 放宽过滤：只要标题或摘要包含地区词就保留
                combined = f"{title} {summary}".lower()
                region_words = ["middle east", "gulf", "saudi", "iran", "arab",
                                "qatar", "uae", "bahrain", "oman", "kuwait",
                                "hormuz", "mena", "riyadh", "doha", "tehran"]
                if not any(w in combined for w in region_words):
                    continue

                date_str = parse_date(date_raw) if date_raw else None
                if date_str and not is_recent(date_str):
                    continue

                articles.append(Article(
                    source_id="brookings_cmep",
                    source_name="Brookings Center for Middle East Policy",
                    title=title,
                    url=url,
                    date=date_str,
                    content_type="article",
                    gcc_keywords=match_gcc(f"{title} {summary}"),
                ))
                seen_urls.add(url)
        except Exception as e:
            log.warning(f"  Brookings API error for '{search_term}': {e}")
        pause()

        if len(articles) >= max_items:
            break

    # 去重 + 限量
    articles = list({a.url: a for a in articles}.values())[:max_items]
    log.info(f"Brookings CMEP: {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════════
# 2. AL JAZEERA CENTRE FOR STUDIES (AJCS)
# ═══════════════════════════════════════════════════════════════
#
# 问题根因：关键词太严，AJCS的GCC文章标题里
#           常出现 "Gulf" / "Hormuz" / "Red Sea" 而不是 "Saudi Arabia"
#
# 修复：扩充关键词 + 在 analysis 页面放宽过滤
#       结构验证：<h4><a href="/en/analyses/slug">Title</a></h4>
#                 日期在 <h4> 的父元素文本里，格式 "17 March 2026"
#
# ═══════════════════════════════════════════════════════════════

AJCS_SECTIONS = [
    ("analysis",     "https://studies.aljazeera.net/en/reports",       "analysis"),
    ("policy_brief", "https://studies.aljazeera.net/en/policy-briefs", "policy_brief"),
    ("publication",  "https://studies.aljazeera.net/en/publications",  "publication"),
]

def scrape_ajcs(test_mode: bool = False) -> list[Article]:
    max_per_section = 5 if test_mode else 30
    articles = []
    seen_urls = set()

    for section_id, url, ctype in AJCS_SECTIONS:
        log.info(f"AJCS [{section_id}] → {url}")
        soup = fetch(url)
        if not soup:
            pause()
            continue

        # 验证结构：<h4> 里有 <a>，日期在父元素文本
        h4_tags = soup.find_all("h4")
        log.info(f"  Found {len(h4_tags)} <h4> items")

        # DEBUG：打印前3个标题，方便排查
        for i, h4 in enumerate(h4_tags[:3]):
            a = h4.find("a")
            if a:
                log.info(f"  Sample {i+1}: {a.get_text(strip=True)[:70]}")

        count = 0
        for h4 in h4_tags:
            a_tag = h4.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not title or len(title) < 10:
                continue

            full_url = urljoin("https://studies.aljazeera.net", href)
            if full_url in seen_urls:
                continue
            if is_event(title):
                continue

            # 找日期（父元素文本）
            date_str = None
            parent = h4.parent
            if parent:
                date_str = extract_date_from_text(parent.get_text(" "))

            if date_str and not is_recent(date_str):
                continue

            # 关键词过滤
            if not is_gcc_relevant(title):
                continue

            articles.append(Article(
                source_id="ajcs",
                source_name="Al Jazeera Centre for Studies",
                title=title,
                url=full_url,
                date=date_str,
                content_type=ctype,
                gcc_keywords=match_gcc(title),
            ))
            seen_urls.add(full_url)
            count += 1
            if count >= max_per_section:
                break

        log.info(f"  AJCS [{section_id}]: {count} GCC-relevant items")
        pause()

    # 尝试抓 archive 页获取更多历史内容
    if not test_mode and len(articles) < 10:
        log.info("AJCS: fetching archive for more content...")
        archive_url = "https://studies.aljazeera.net/en/reports/archive"
        soup = fetch(archive_url)
        if soup:
            for h4 in soup.find_all("h4"):
                a_tag = h4.find("a", href=True)
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True)
                href = a_tag["href"]
                if len(title) < 10:
                    continue
                full_url = urljoin("https://studies.aljazeera.net", href)
                if full_url in seen_urls:
                    continue
                if not is_gcc_relevant(title):
                    continue
                date_str = extract_date_from_text(h4.parent.get_text(" ") if h4.parent else "")
                if date_str and not is_recent(date_str):
                    continue
                articles.append(Article(
                    source_id="ajcs",
                    source_name="Al Jazeera Centre for Studies",
                    title=title,
                    url=full_url,
                    date=date_str,
                    content_type="analysis",
                    gcc_keywords=match_gcc(title),
                ))
                seen_urls.add(full_url)

    log.info(f"AJCS total: {len(articles)} articles")
    return articles


# ═══════════════════════════════════════════════════════════════
# 3. RASANAH — International Institute for Iranian Studies
# ═══════════════════════════════════════════════════════════════
#
# 问题根因（已确认）：
#   Rasanah 的文章链接是完整URL（https://rasanah-iiis.org/english/...）
#   原代码判断 "rasanah-iiis.org" not in href → 条件永远为False
#   → href = urljoin(...) 这行从未执行 → 没问题
#   真正的问题：h2 找到了但随后的 is_event() 或 关键词过滤 把所有文章都排掉了
#
# 重新验证：从fetch到的真实HTML看，Rasanah的h2结构：
#   <h2><a href="https://rasanah-iiis.org/english/news/...">标题</a></h2>
#   日期在 h2 外面，格式 "04:14 pm - 12 Feb 2026"
#
# 修复：
#   1. 放宽关键词（Rasanah内容都是沙特/海湾视角，几乎全收）
#   2. 日期正则同时匹配 "12 Feb 2026" 和 "12 February 2026"
#   3. 加调试日志，打印前几条h2内容方便排查
#
# ═══════════════════════════════════════════════════════════════

RASANAH_SECTIONS = [
    # /category/ 페이지는 사이드바 링크만 반환 확인 → 실제 콘텐츠 URL로 교체
    ("main",        "https://rasanah-iiis.org/english/",                                    "research"),
    ("reports",     "https://rasanah-iiis.org/english/monitoring-and-translation/reports/", "report"),
    ("search_gcc",  "https://rasanah-iiis.org/english/?s=gulf+saudi+arabia",               "research"),
    ("search_iran", "https://rasanah-iiis.org/english/?s=iran+gulf+states",                "research"),
]

# Rasanah 内容几乎全部和伊朗-海湾关系有关，用宽松词表
RASANAH_BROAD_KEYWORDS = [
    "gulf", "saudi", "uae", "emirates", "bahrain", "kuwait",
    "qatar", "oman", "gcc", "riyadh", "arab", "doha",
    "hormuz", "red sea", "houthi", "yemen", "iran-",
    "vision 2030", "aramco", "opec",
]

def rasanah_is_relevant(title: str, url: str) -> bool:
    """Rasanah专用相关性判断（更宽松）"""
    combined = f"{title} {url}".lower()
    # 命中标准GCC词
    if is_gcc_relevant(title):
        return True
    # 命中宽松词
    if any(w in combined for w in RASANAH_BROAD_KEYWORDS):
        return True
    # Rasanah 的研究类文章默认相关（伊朗研究 = 海湾视角）
    if "/centre-for-researches-and-studies/" in url:
        return True
    if "/position-estimate/" in url:
        return True
    return False

def scrape_rasanah_page(url: str, ctype: str, seen: set, max_items: int) -> list[Article]:
    articles = []
    soup = fetch(url)
    if not soup:
        return articles

    # ── 结构诊断 ──────────────────────────────────────────────
    # Log发现：找到120个<h2>但0篇文章，说明<h2>里没有<a href>
    # 真实结构（Rasanah WordPress主题）：
    #   <a href="https://rasanah-iiis.org/english/news/title-slug/">
    #     <h2>标题文字</h2>       ← <a>在<h2>外面包着
    #   </a>
    # 或：
    #   <h2 class="...">
    #     <a href="...">标题</a>  ← 正常结构但<a>里是空字符串
    #   </h2>
    #   (另一个<a>在图片上，链接相同)
    #
    # 解决：直接找所有指向 rasanah-iiis.org/english 的<a>链接
    #       用链接文字或相邻<h2>的文字作为标题
    # ─────────────────────────────────────────────────────────

    # 只保留文章链接，排除导航/工具类页面
    # log确认：/about-us/ /contact-us/ /joined-the-institute/ 是导航链接混入了
    # Rasanah文章URL规律（只保留这些路径）：
    RASANAH_ARTICLE_PATHS = [
        "/english/news/", "/english/monitoring-and-translation/",
        "/english/centre-for-researches-and-studies/",
        "/english/position-estimate/", "/english/publications/",
        "/english/the-journal/",
    ]
    RASANAH_EXCLUDE_PATHS = [
        "/category/", "/page/", "/about-us", "/contact-us",
        "/joined-the-institute", "/author/", "/tag/", "/policy-advice",
        "/partnerships", "/board-of-trustees", "/executive-department",
        "/multimedia", "/infographics", "/video", "arabiangcis.org",
    ]
    # 先定位主体内容区 div#main，排除侧边栏（已通过浏览器Inspect确认）
    main = soup.find("div", id="main") or soup
    title_tags = main.find_all("h2", class_="the-title")
    log.info(f"    Found {len(title_tags)} article titles in main content")

    for h2 in title_tags:
        # 标题文字
        title = h2.get_text(strip=True)
        if not title or len(title) < 8:
            continue

        # 结构已确认：<li> > <a class="single-post clearfix"> > <div class="text"> > <h2>
        # 链接在 h2 的祖先 <a> 里，需要向上找
        a_tag = None
        node = h2.parent  # div.text
        for _ in range(4):
            if node is None:
                break
            if node.name == "a" and node.get("href"):
                a_tag = node
                break
            node = node.parent
        if not a_tag:
            continue

        href = a_tag["href"]
        if not href.startswith("http"):
            href = urljoin("https://rasanah-iiis.org", href)
        if href in seen:
            continue
        if is_event(title):
            continue

        # 找日期：在 h2 的父元素附近找 "12 Feb 2026" 格式
        date_str = None
        parent = h2.parent
        for _ in range(5):
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            m = re.search(
                r"\b(\d{1,2})\s+"
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
                r"|January|February|March|April|May|June|July|August"
                r"|September|October|November|December)\s+"
                r"(\d{4})\b",
                text, re.IGNORECASE
            )
            if m:
                date_str = parse_date(f"{m.group(1)} {m.group(2)} {m.group(3)}")
                break
            parent = parent.parent

        if date_str and not is_recent(date_str):
            log.info(f"    SKIP (too old: {date_str}): {title[:50]}")
            continue
        if not rasanah_is_relevant(title, href):
            log.info(f"    SKIP (not relevant): {title[:50]}")
            continue

        log.info(f"    ADD: {title[:60]}")
        articles.append(Article(
            source_id="rasanah",
            source_name="Rasanah — International Institute for Iranian Studies",
            title=title,
            url=href,
            date=date_str,
            content_type=ctype,
            gcc_keywords=match_gcc(title),
        ))
        seen.add(href)
        if len(articles) >= max_items:
            break

    return articles

def scrape_rasanah(test_mode: bool = False) -> list[Article]:
    max_per_section = 5 if test_mode else 25
    max_pages = 1 if test_mode else 3
    articles = []
    seen_urls = set()

    for section_id, base_url, ctype in RASANAH_SECTIONS:
        log.info(f"Rasanah [{section_id}]")
        section_articles = []

        for page_num in range(1, max_pages + 1):
            url = base_url if page_num == 1 else f"{base_url}page/{page_num}/"
            log.info(f"  Page {page_num}: {url}")
            items = scrape_rasanah_page(url, ctype, seen_urls, max_per_section)
            section_articles.extend(items)
            log.info(f"  → {len(items)} items")

            if len(items) == 0 or len(section_articles) >= max_per_section:
                break
            pause()

        log.info(f"  Rasanah [{section_id}]: {len(section_articles)} total")
        articles.extend(section_articles)
        pause()

    log.info(f"Rasanah total: {len(articles)} articles")
    return articles


# ══════════════════════════════════════════════
# 输出
# ══════════════════════════════════════════════

def save(articles: list[Article], label: str, output_dir: str = "output"):
    Path(output_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    json_path = f"{output_dir}/gcc_{label}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in articles], f, ensure_ascii=False, indent=2)

    csv_path = f"{output_dir}/gcc_{label}_{ts}.csv"
    fields = ["source_name", "title", "date", "content_type",
              "authors", "url", "gcc_keywords", "scraped_at"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for a in articles:
            row = asdict(a)
            row["authors"] = ", ".join(row.get("authors") or [])
            row["gcc_keywords"] = ", ".join(row.get("gcc_keywords") or [])
            w.writerow(row)

    log.info(f"Saved {len(articles)} → {json_path} + {csv_path}")
    return json_path, csv_path

def print_summary(articles: list[Article]):
    from collections import Counter
    print("\n" + "=" * 55)
    print("  GCC SCRAPER v2 — 结果摘要")
    print("=" * 55)
    print(f"  总计: {len(articles)} 篇")
    for src, n in Counter(a.source_id for a in articles).most_common():
        print(f"  {src:40s} {n:3d} 篇")
    kws = Counter(k for a in articles for k in a.gcc_keywords)
    if kws:
        print("\n  命中关键词 Top 10:")
        for kw, n in kws.most_common(10):
            print(f"    {kw:35s} {n}")
    print("=" * 55)


# ══════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["brookings", "ajcs", "rasanah"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()

    if not args.source and not args.all:
        parser.print_help()
        return

    all_articles = []

    if args.source == "brookings" or args.all:
        log.info("━━━ Brookings CMEP ━━━")
        items = scrape_brookings(test_mode=args.test)
        all_articles.extend(items)
        save(items, "brookings", args.output)

    if args.source == "ajcs" or args.all:
        log.info("━━━ Al Jazeera Centre for Studies ━━━")
        items = scrape_ajcs(test_mode=args.test)
        all_articles.extend(items)
        save(items, "ajcs", args.output)

    if args.source == "rasanah" or args.all:
        log.info("━━━ Rasanah ━━━")
        items = scrape_rasanah(test_mode=args.test)
        all_articles.extend(items)
        save(items, "rasanah", args.output)

    if args.all and all_articles:
        merged = list({a.url: a for a in all_articles}.values())
        merged.sort(key=lambda x: x.date or "0000", reverse=True)
        save(merged, "all_sources", args.output)
        print_summary(merged)


if __name__ == "__main__":
    main()
