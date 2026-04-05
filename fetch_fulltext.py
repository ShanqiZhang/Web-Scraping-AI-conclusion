#!/usr/bin/env python3
"""
fetch_fulltext.py — 正文抓取
==============================
读取 scrapers_v2.py 生成的 CSV，
对每篇文章跟进URL抓取正文内容，
输出带正文的新CSV。

用法:
    python fetch_fulltext.py --input output/gcc_all_sources_20260322_2029.csv
    python fetch_fulltext.py --input output/gcc_all_sources_20260322_2029.csv --test
"""

import requests
from bs4 import BeautifulSoup
import csv
import time
import re
import argparse
import logging
import io
from pathlib import Path
from datetime import datetime

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("fulltext.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("fetch_fulltext")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})
DELAY = 3.0  # 正文抓取间隔稍长，更礼貌


def fetch(url: str) -> BeautifulSoup | None:
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=20, allow_redirects=True)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except requests.RequestException as e:
            wait = 2 ** attempt
            log.warning(f"  Attempt {attempt+1}/3 failed: {e} — retry in {wait}s")
            time.sleep(wait)
    log.error(f"  Failed: {url}")
    return None


def clean_text(text: str) -> str:
    """清理文本：去除多余空白、换行"""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ══════════════════════════════════════════════
# Rasanah 正文提取
# 结构：标题在 <h1>，正文在 <div class="single-content"> 或直接是 <p> 段落
# ══════════════════════════════════════════════
def extract_rasanah(soup: BeautifulSoup) -> dict:
    result = {"full_text": "", "authors": "", "word_count": 0}

    # 正文容器：尝试多个可能的class
    content_div = (
        soup.find("div", class_="single-content") or
        soup.find("div", class_="post-content") or
        soup.find("div", class_="entry-content") or
        soup.find("article")
    )

    if not content_div:
        # 兜底：找 div#main 里所有 <p> 标签
        main = soup.find("div", id="main")
        if main:
            paragraphs = main.find_all("p")
        else:
            paragraphs = soup.find_all("p")
    else:
        paragraphs = content_div.find_all("p")

    # 过滤掉太短的段落（导航文字等）
    text_parts = []
    for p in paragraphs:
        text = clean_text(p.get_text())
        if len(text) > 40:  # 超过40字符才算正文段落
            text_parts.append(text)

    result["full_text"] = "\n\n".join(text_parts)
    result["word_count"] = len(result["full_text"].split())

    # 作者
    author_tag = (
        soup.find("a", class_="author") or
        soup.find(class_=re.compile(r"author", re.I))
    )
    if author_tag:
        result["authors"] = clean_text(author_tag.get_text())

    return result


# ══════════════════════════════════════════════
# AJCS 正文提取
# 结构：正文在 <div class="field--name-body"> 或 <article> 里的 <p>
# ══════════════════════════════════════════════
def extract_ajcs(soup: BeautifulSoup) -> dict:
    result = {"full_text": "", "authors": "", "word_count": 0}

    # AJCS结构：正文是页面里的<p>段落，在标题和footer之间
    # 策略：找 <main> 或 <article> 容器，再提取<p>
    # 排除导航、footer、related articles等
    # AJCS结构已确认（通过Inspect）：
    # <div class="field field--name-body field--type-text-with-summary field--label-hidden field--item">
    #   <p class="text-align-justify">正文段落</p>
    # AJCS页面里 field--name-body 出现5次（搜索框、导航、正文、footer等）
    # 需要找到第一个包含真正<p>段落的那个（第4个）
    candidates = soup.find_all("div", class_=lambda c: c and "field--name-body" in c)
    main = None
    for candidate in candidates:
        # 真正的正文容器里有实质性的<p>段落
        paras = [p for p in candidate.find_all("p") if len(p.get_text(strip=True)) > 60]
        if len(paras) >= 2:  # 至少两个实质段落才算正文
            main = candidate
            break

    if main:
        paragraphs = main.find_all("p")
    else:
        paragraphs = soup.find_all("p")

    text_parts = []
    for p in paragraphs:
        text = clean_text(p.get_text())
        # 过滤太短、或像导航文字的段落
        if len(text) > 60:
            text_parts.append(text)

    result["full_text"] = "\n\n".join(text_parts)
    result["word_count"] = len(result["full_text"].split())

    # 作者：AJCS文章里作者名在 <h4> 或 <a> 标签里，class含profile
    author_tag = (
        soup.find("a", href=re.compile(r"/profile/")) or
        soup.find(class_=re.compile(r"author", re.I))
    )
    if author_tag:
        result["authors"] = clean_text(author_tag.get_text())

    return result


# ══════════════════════════════════════════════
# PDF 提取
# 策略：在页面HTML里找 .pdf 链接，下载后用 pdfplumber 提取文字
# ══════════════════════════════════════════════
def find_pdf_url(soup: BeautifulSoup, base_url: str) -> str:
    """在页面里找PDF下载链接"""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            # 补全相对路径
            if href.startswith("http"):
                return href
            else:
                from urllib.parse import urljoin
                return urljoin(base_url, href)
    return ""

def extract_pdf_text(pdf_url: str) -> str:
    """下载PDF并提取文字"""
    if not HAS_PDF:
        log.warning("  pdfplumber未安装，跳过PDF提取")
        return ""
    try:
        log.info(f"  下载PDF: {pdf_url}")
        r = SESSION.get(pdf_url, timeout=30)
        r.raise_for_status()
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
            full_text = "\n\n".join(pages)
            log.info(f"  PDF提取完成：{len(full_text.split())} 词，{len(pdf.pages)} 页")
            return full_text
    except Exception as e:
        log.error(f"  PDF提取失败: {e}")
        return ""


# ══════════════════════════════════════════════
# 路由：根据来源选择提取函数
# ══════════════════════════════════════════════
def extract_fulltext(url: str, source_id: str, soup: BeautifulSoup) -> dict:
    if "rasanah" in url or "rasanah" in source_id.lower():
        return extract_rasanah(soup)
    elif "aljazeera" in url or "ajcs" in source_id.lower():
        return extract_ajcs(soup)
    else:
        # 通用兜底
        return extract_rasanah(soup)


# ══════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="输入CSV文件路径")
    parser.add_argument("--test", action="store_true", help="测试模式，只抓前3篇")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"文件不存在: {input_path}")
        return

    # 读取输入CSV
    with open(input_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info(f"读取 {len(rows)} 篇文章，开始抓取正文...")

    if args.test:
        rows = rows[:3]
        log.info("测试模式：只抓前3篇")

    # 输出CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = input_path.parent / f"gcc_fulltext_{ts}.csv"
    fields = list(rows[0].keys()) + ["full_text", "word_count"]

    results = []
    for i, row in enumerate(rows, 1):
        url = row.get("url", "")
        title = row.get("title", "")[:60]
        source = row.get("source_name", "")

        log.info(f"[{i}/{len(rows)}] {title}...")

        if not url:
            log.warning("  No URL, skipping")
            row["full_text"] = ""
            row["word_count"] = 0
            results.append(row)
            continue

        soup = fetch(url)
        if not soup:
            row["full_text"] = ""
            row["word_count"] = 0
            results.append(row)
            time.sleep(DELAY)
            continue

        extracted = extract_fulltext(url, source, soup)
        row["full_text"] = extracted["full_text"]
        row["word_count"] = extracted["word_count"]

        # 如果正文太短（少于100词），尝试找页面里的PDF链接
        if extracted["word_count"] < 100:
            pdf_url = find_pdf_url(soup, url)
            if pdf_url:
                log.info(f"  正文太短（{extracted['word_count']}词），尝试PDF: {pdf_url}")
                pdf_text = extract_pdf_text(pdf_url)
                if len(pdf_text.split()) > extracted["word_count"]:
                    row["full_text"] = pdf_text
                    row["word_count"] = len(pdf_text.split())
                    log.info(f"  PDF替换成功：{row['word_count']} 词")
            else:
                log.info(f"  正文太短（{extracted['word_count']}词），页面无PDF链接")

        # 如果原来没有作者，用抓到的
        if not row.get("authors") and extracted.get("authors"):
            row["authors"] = extracted["authors"]

        log.info(f"  ✅ {extracted['word_count']} words extracted")
        results.append(row)
        time.sleep(DELAY)

    # 保存
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    success = sum(1 for r in results if r.get("word_count", 0) > 0)
    log.info(f"\n完成：{success}/{len(results)} 篇成功抓取正文")
    log.info(f"输出文件：{output_path}")


if __name__ == "__main__":
    main()
