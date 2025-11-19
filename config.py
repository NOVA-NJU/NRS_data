"""Centralized configuration knobs for the crawler service."""

from __future__ import annotations

import os


def _get_bool_env(name: str, default: bool) -> bool:
    """Parse boolean environment flags with sensible defaults."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# 服务端口
CRAWLER_PORT = int(os.getenv("CRAWLER_PORT", "8001"))

# 爬虫设置
CRAWL_INTERVAL = int(os.getenv("CRAWL_INTERVAL", "3600"))  # 爬取间隔(秒)
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
AUTO_CRAWL_ENABLED = _get_bool_env("AUTO_CRAWL_ENABLED", True)

# 向量服务配置
VECTOR_SERVICE = {
    "enabled": True,
    "base_url": os.getenv("VECTOR_SERVICE_BASE_URL", "http://localhost:8000"),  # 后端 2 服务地址或本地 mock
    "timeout": 10,
    "api_key": None,
}

# OCR 配置
TESSERACT_CMD = r"D:\Apps\tesseract\tesseract.exe"
TESSDATA_DIR = r"D:\Apps\tesseract\tessdata"

# 数据库配置
DATABASE_PATH = "./data/crawler.db"

# 目标网站列表
TARGET_SOURCES = [
    {
        'id' : 'bksy_ggtz',
        'name' : '本科生院-公告通知',
        'base_url' : 'https://jw.nju.edu.cn',
        'list_url' : 'https://jw.nju.edu.cn/ggtz/list1.htm',
        'max_pages': 5,  # 测试阶段最多抓取前 5 页
        'headers' : {
            'USER_AGENT' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0',
            'host' : 'jw.nju.edu.cn'
        },
        'selectors' : {
            'item_container' : '#wp_news_w6 li.news',
            'date' : '.news_meta', #::text
            'title' : '.news_title a',#::text
            'url' : '.news_title a',#::attr(href)
            'type' : '.wjj .lj'#::text
        },
		'detail_selector' : '#d-container .wp_articlecontent p'#::text
    }
]

DETAIL_SELECTORS = {
    # 对不同类型数据使用不同选择器
    'meta_selector':{
        'item_container' : '#d-container',
        'publisher': '.arti_publisher',
        'views': '.arti_views',
    },
    'text_selector':{
        'item_container' : '#d-container',
        'content' : '.wp_articlecontent',
    },
    'img_selector':{
        'item_container' : '#d-container',
        'images' : '.wp_articlecontent img[src]',
    },
    'pdf_selector':{
        'item_container' : '#d-container',
        'files' : '.wp_articlecontent a[href$=".pdf"]',
        'name' : '.wp_articlecontent a[href$=".pdf"] span'
    },
    'doc_selector':{
        'item_container' : '#d-container',
        'files' : '.wp_articlecontent a[href$=".doc"], .wp_articlecontent a[href$=".docx"]',
        'name' : '.wp_articlecontent a[href$=".doc"], .wp_articlecontent a[href$=".docx"]'
    },
    'embedded_pdf_selector':{
        'item_container' : '#d-container',
        'viewer' : '.wp_articlecontent iframe.wp_pdf_player',
        'download_link' : '.wp_articlecontent img[src$="icon_pdf.gif"] + a'
    },
}
