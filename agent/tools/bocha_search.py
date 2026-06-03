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
Bocha 网络搜索工具模块
"""

import httpx
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class BochaSearchInput(BaseModel):
    query: str = Field(description="搜索关键词")
    freshness: Optional[str] = Field(
        default=None,
        description="时间范围过滤：noLimit(默认)、oneDay、oneWeek、oneMonth、oneYear、YYYY-MM-DD..YYYY-MM-DD"
    )
    search_type: Optional[str] = Field(
        default="webPages",
        description="搜索结果类型：webPages(默认，Web网页内容)、images(图片内容)、videos(视频内容)"
    )
    count: Optional[int] = Field(default=None, description="返回结果数量，默认10")
    include: Optional[str] = Field(default=None, description="仅包含指定域名，如 example.com")
    exclude: Optional[str] = Field(default=None, description="排除指定域名")


class BochaSearchTool(BaseTool):
    """Bocha 网络搜索工具"""

    name: str = "web_search"
    description: str = "搜索网络信息，获取实时网页搜索结果"
    args_schema: type[BaseModel] = BochaSearchInput

    api_key: str
    api_url: str = "https://api.bocha.cn/v1/web-search"
    default_count: int = 10
    default_freshness: str = "noLimit"

    def _run(
        self,
        query: str,
        freshness: Optional[str] = None,
        search_type: Optional[str] = "webPages",
        count: Optional[int] = None,
        include: Optional[str] = None,
        exclude: Optional[str] = None
    ) -> str:
        """执行搜索"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "query": query,
                "summary": True,
                "freshness": freshness or self.default_freshness,
                "count": count or self.default_count
            }

            if include:
                payload["include"] = include
            if exclude:
                payload["exclude"] = exclude

            with httpx.Client(timeout=60) as client:
                response = client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                if search_type == "images":
                    # 格式化搜索结果
                    return self._format_results(result, "images")
                elif search_type == "videos":
                    # 格式化搜索结果
                    return self._format_results(result, "videos")
                else:
                    # 格式化搜索结果
                    return self._format_results(result, "webPages")

        except Exception as e:
            return f"网络搜索出错: {str(e)}"

    def _format_results(self, result: Dict[str, Any], search_type: str) -> str:
        """格式化搜索结果"""
        if isinstance(result, str):
            return result

        if "data" in result:
            results = result["data"]
            type_category = results.get(search_type, {})
            if not type_category:
                type_category = {}
            items = type_category.get("value", [])
            return str(items)

        return str(result)


def create_bocha_tool(api_url: str, api_key: str) -> BochaSearchTool:
    """
    创建 Bocha 搜索工具
    """
    return BochaSearchTool(
        api_key=api_key,
        api_url=api_url,
        default_count=10,
        default_freshness="noLimit"
    )
