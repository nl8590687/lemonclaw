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
文件列表查询工具 - 递归查询指定目录下的文件和文件夹
"""
import json
from pathlib import Path
from typing import Dict, Optional, Type, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class FileListQueryInput(BaseModel):
    """文件列表查询工具的输入"""
    path: str = Field(description="要查询的目录路径（支持相对路径如 \".\"、\"..\"）")
    recursive: bool = Field(default=False, description="是否递归查询所有子目录，默认为 False（仅查询一层）")


class FileListQueryTool(BaseTool):
    """文件列表查询工具"""

    name: str = "query_file_list"
    description: str = "查询指定目录下的文件和文件夹列表。参数 path 为目录路径（支持相对路径如 \".\"、\"..\"），recursive 控制是否递归查询所有子目录。需要在配置文件中设置允许访问的安全目录前缀。"
    args_schema: Type[BaseModel] = FileListQueryInput

    # 使用 model_config 允许额外字段
    model_config = {"extra": "allow"}

    def __init__(self, safe_dirs: list[str]):
        """
        初始化工具

        Args:
            safe_dirs: 安全目录列表
        """
        super().__init__()
        self._safe_dirs: List[str] = safe_dirs
        # 自动添加当前工作目录到安全目录（如果没配置）
        if not self._safe_dirs:
            self._safe_dirs.append(str(Path.cwd().resolve()))

    def _is_path_safe(self, target_path: str) -> bool:
        """
        检查路径是否安全，防止路径穿越

        Args:
            target_path: 要检查的目标路径

        Returns:
            bool: 路径是否安全
        """
        if not self._safe_dirs:
            return False

        try:
            target_abs = Path(target_path).resolve()

            for safe_dir in self._safe_dirs:
                safe_abs = Path(safe_dir).resolve()
                try:
                    target_abs.relative_to(safe_abs)
                    return True
                except ValueError:
                    continue

            return False
        except Exception:
            return False

    def _run(self, *args, **kwargs) -> str:
        """
        查询目录下的文件和文件夹

        Args:
            path: 要查询的目录路径（支持相对路径如 "."、".." 等）
            dir_path: 备用参数名，兼容旧调用方式
            recursive: 是否递归查询所有子目录

        Returns:
            str: 查询结果
        """
        # 处理 LangChain 传入整个 JSON 作为第一个参数的情况
        path: Optional[str] = None
        dir_path: Optional[str] = None
        recursive: bool = False

        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                # 尝试解析 JSON
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        path = parsed.get("path") or parsed.get("dir_path")
                        recursive = parsed.get("recursive", False)
                except Exception:
                    # 不是 JSON，当作普通路径
                    path = first_arg
            elif isinstance(first_arg, dict):
                path = first_arg.get("path") or first_arg.get("dir_path")
                recursive = first_arg.get("recursive", False)

        # 从 kwargs 中获取参数
        if not path:
            path = kwargs.get("path")
        if not path:
            dir_path = kwargs.get("dir_path")
            path = dir_path
        if "recursive" in kwargs:
            recursive = kwargs["recursive"]

        # 兼容两种参数名
        target_path = path or dir_path
        if not target_path:
            # 如果都没提供，使用当前目录
            target_path = "."

        if not self._safe_dirs:
            config_hint = f"配置文件: {self._config_path}" if self._config_path else ""
            return f"错误：未配置安全目录列表。{config_hint}"

        try:
            # 解析相对路径为绝对路径
            target_dir = Path(target_path).resolve()

            if not self._is_path_safe(str(target_dir)):
                return f"错误：路径不在允许的安全目录列表中。安全目录前缀: {self._safe_dirs}"

            if not target_dir.exists():
                return f"错误：目录不存在 - {target_path}"

            if not target_dir.is_dir():
                return f"错误：指定路径不是目录 - {target_path}"

            files: List[Dict] = []
            directories: List[Dict] = []

            if recursive:
                for item in target_dir.rglob("*"):
                    rel_path = str(item.relative_to(target_dir))

                    if item.is_file():
                        files.append({
                            "path": str(item),
                            "relative_path": rel_path,
                            "name": item.name,
                            "size": item.stat().st_size
                        })
                    elif item.is_dir():
                        directories.append({
                            "path": str(item),
                            "relative_path": rel_path,
                            "name": item.name
                        })
            else:
                for item in target_dir.iterdir():
                    rel_path = item.name

                    if item.is_file():
                        files.append({
                            "path": str(item),
                            "relative_path": rel_path,
                            "name": item.name,
                            "size": item.stat().st_size
                        })
                    elif item.is_dir():
                        directories.append({
                            "path": str(item),
                            "relative_path": rel_path,
                            "name": item.name
                        })

            result = {
                "success": True,
                "directory": str(target_dir),
                "recursive": recursive,
                "files": files,
                "directories": directories,
                "file_count": len(files),
                "directory_count": len(directories)
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


def create_file_list_query_tool(safe_dirs: list[str]) -> FileListQueryTool:
    """
    创建文件列表查询工具

    Args:
        safe_dirs: 安全目录列表

    Returns:
        FileListQueryTool: 文件列表查询工具实例
    """
    return FileListQueryTool(safe_dirs)
