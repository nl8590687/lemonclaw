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
HTTP Request 工具模块
"""

import re
import json
import httpx
from langchain_core.tools import tool


@tool
def http_request(method: str = "GET", url: str = "", headers: dict[str, object]|None = None, body: str|None = None) -> str:
    """
    发起 HTTP 请求获取网页内容，支持 GET/POST/PUT/DELETE 等方法。
    注意：该工具仅用于抓取网页原文和API接口调用，不能用于长文本文件和二进制文件下载等场景。

    Args:
        method(str): HTTP请求方法：GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS
        url(str): 请求链接，必须以 http:// 或 https:// 开头
        headers(dict[str, object]|None): 请求头，JSON 对象格式
        body(str): 请求体，仅用于 POST/PUT/PATCH 方法

    Returns:
        请求结果字符串
    """
    if not url:
        return "错误: url 参数不能为空"

    if not re.match(r'^https?://', url):
        return "错误: url 必须以 http:// 或 https:// 开头"

    method = method.upper()
    valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']
    if method not in valid_methods:
        return f"错误: 无效的 HTTP 方法 {method}，支持的方法: {', '.join(valid_methods)}"

    # 确保 headers 是 dict
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except json.JSONDecodeError:
            headers = {}

    if not isinstance(headers, dict):
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            request_args = {
                "method": method,
                "url": url,
                "headers": headers
            }

            if method in ['POST', 'PUT', 'PATCH'] and body:
                request_args["content"] = body

            response = client.request(**request_args)

            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"HTTP 请求失败: {str(e)}"


def create_http_request_tool():
    """
    创建 HTTP Request 工具
    """
    return http_request
