# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Web Fetch 工具模块

与 http_request 工具的区别：
- 固定使用 GET 方法抓取网页内容
- 自动清洗处理 HTML 内容
- 转换为干净易读的 Markdown 或纯文本
- 剔除无关的脚本、CSS 和广告

使用场景：
- 需要阅读普通网页、提取文章内容
- 获取结构化文本时，省去繁琐的数据清洗步骤

与 http_request 的选择：
- 优先使用 web_fetch：阅读网页、提取文章、获取结构化文本
- 选择 http_request：请求 API 接口、下载文件、追求最高效率
"""

import re
import json
import html
import httpx
from langchain_core.tools import tool


def _basic_clean(html_content: str) -> str:
    """基础 HTML 清洗"""
    # 解码 HTML 实体
    html_content = html.unescape(html_content)
    # 移除特定标签
    html_content = re.sub(r'<script[^>]*?>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*?>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<noscript[^>]*?>.*?</noscript>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<!--.*?-->', '', html_content, flags=re.DOTALL)
    html_content = re.sub(r'<iframe[^>]*?>.*?</iframe>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<link[^>]*?>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<meta[^>]*?>', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'<svg[^>]*?>.*?</svg>', '', html_content, flags=re.DOTALL | re.IGNORECASE)

    return html_content


def _html_to_text(html_content: str) -> str:
    """HTML 转纯文本"""
    text = html_content
    # 替换换行标签
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()


def _process_ul(match: re.Match) -> str:
    """处理无序列表"""
    content = match.group(1)
    content = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', content, flags=re.DOTALL | re.IGNORECASE)
    return f'\n{content}\n'


def _process_ol(match: re.Match) -> str:
    """处理有序列表"""
    content = match.group(1)
    items = re.findall(r'<li[^>]*>(.*?)</li>', content, flags=re.DOTALL | re.IGNORECASE)
    result = [f'{i}. {item}' for i, item in enumerate(items, 1)]
    return f'\n' + '\n'.join(result) + '\n'


def _process_table(match: re.Match) -> str:
    """处理表格（简化）"""
    content = match.group(1)
    text = re.sub(r'<[^>]+>', ' ', content)
    text = re.sub(r'\s+', ' ', text).strip()
    return f'\n[表格内容: {text}]\n'


def _html_to_markdown(html_content: str) -> str:
    """HTML 转 Markdown"""
    md = html_content

    # 处理标题
    md = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h4[^>]*>(.*?)</h4>', r'\n#### \1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h5[^>]*>(.*?)</h5>', r'\n##### \1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<h6[^>]*>(.*?)</h6>', r'\n###### \1\n', md, flags=re.DOTALL | re.IGNORECASE)

    # 处理段落和换行
    md = re.sub(r'<p[^>]*>(.*?)</p>', r'\n\1\n', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)

    md = re.sub(r'<ul[^>]*>(.*?)</ul>', _process_ul, md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<ol[^>]*>(.*?)</ol>', _process_ol, md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1', md, flags=re.DOTALL | re.IGNORECASE)

    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.DOTALL | re.IGNORECASE)

    md = re.sub(r'<(b|strong)[^>]*>(.*?)</\1>', r'**\2**', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<(i|em)[^>]*>(.*?)</\1>', r'*\2*', md, flags=re.DOTALL | re.IGNORECASE)

    md = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r'<pre[^>]*>(.*?)</pre>', r'```\n\1\n```', md, flags=re.DOTALL | re.IGNORECASE)

    md = re.sub(r'<img[^>]*src="([^"]*)"[^>]*alt="([^"]*)"[^>]*>', r'![\2](\1)', md, flags=re.IGNORECASE)
    md = re.sub(r'<img[^>]*src="([^"]*)"[^>]*>', r'![](\1)', md, flags=re.IGNORECASE)

    md = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> \1', md, flags=re.DOTALL | re.IGNORECASE)

    md = re.sub(r'<hr\s*/?>', '\n---\n', md, flags=re.IGNORECASE)

    md = re.sub(r'<table[^>]*>(.*?)</table>', _process_table, md, flags=re.DOTALL | re.IGNORECASE)

    # 清理空白
    md = re.sub(r'<[^>]+>', '', md)
    md = re.sub(r'[ \t]+', ' ', md)
    md = re.sub(r'\n\s*\n\s*\n', '\n\n', md)

    return md.strip()


def _clean_html(html_content: str, output_format: str) -> str:
    """清洗 HTML 内容"""
    cleaned = _basic_clean(html_content)
    if output_format == "markdown":
        return _html_to_markdown(cleaned)
    else:
        return _html_to_text(cleaned)


@tool
def web_fetch(url: str, output_format: str = "markdown") -> str:
    """
    使用 GET 方法抓取网页内容，自动清洗 HTML 并转换为易读的 Markdown 格式，剔除脚本、CSS 和广告。适合阅读网页和提取文章。

    Args:
        url(str): 网页链接，必须以 http:// 或 https:// 开头
        output_format(str): 输出格式：markdown（默认）或 text

    Returns:
        网页内容文本
    """
    if not url:
        return "错误: url 参数不能为空"

    if not re.match(r'^https?://', url):
        return "错误: url 必须以 http:// 或 https:// 开头"

    output_format = output_format.lower()
    if output_format not in ["markdown", "text"]:
        output_format = "markdown"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

            html_content = response.text
            cleaned_content = _clean_html(html_content, output_format)

            result = {
                "status_code": response.status_code,
                "url": str(response.url),
                "output_format": output_format,
                "content": cleaned_content,
                "content_length": len(cleaned_content)
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Web Fetch 失败: {str(e)}"


def create_web_fetch_tool():
    """
    创建 Web Fetch 工具
    """
    return web_fetch
