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

"""Glob 工具 - 根据通配符模式快速查找文件和目录"""
import json
from pathlib import Path
from typing import List, Optional, Type
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GlobToolInput(BaseModel):
    """Glob 工具的输入"""
    pattern: str = Field(
        description="文件匹配模式，支持通配符：* 匹配任意字符（不含路径分隔符），"
                    "** 递归匹配所有子目录，? 匹配单个字符，[] 匹配字符集。"
                    "示例：src/**/*.js、**/*.test.py、**/package.json"
    )
    path: Optional[str] = Field(
        default=None,
        description="搜索的根目录路径。默认为当前工作目录"
    )


class GlobTool(BaseTool):
    """文件模式匹配工具 - 根据通配符模式快速查找文件和目录"""

    name: str = "glob"
    description: str = (
        "根据通配符模式快速查找文件和目录。"
        "支持语法：* 匹配任意字符（不含路径分隔符），** 递归匹配所有子目录，"
        "? 匹配单个字符，[] 匹配字符集。"
        "使用场景：查找特定类型文件（src/**/*.js）、探索项目结构（**/*.test.py）、"
        "定位配置文件（**/package.json）、批量操作前的文件定位。"
    )
    args_schema: Type[BaseModel] = GlobToolInput

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
        pattern: Optional[str] = None
        search_path: Optional[str] = None

        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        pattern = parsed.get("pattern")
                        search_path = parsed.get("path")
                except Exception:
                    pattern = first_arg
            elif isinstance(first_arg, dict):
                pattern = first_arg.get("pattern")
                search_path = first_arg.get("path")

        if not pattern:
            pattern = kwargs.get("pattern")
        if not search_path:
            search_path = kwargs.get("path")

        if not pattern:
            return "错误：必须提供 pattern 参数指定文件匹配模式"

        # 默认搜索目录为当前工作目录
        if not search_path:
            search_path = "."

        if not self._safe_dirs:
            return "错误：未配置安全目录列表"

        try:
            search_dir = Path(search_path).resolve()

            if not self._is_path_safe(str(search_dir)):
                return f"错误：路径不在允许的安全目录列表中。安全目录前缀: {self._safe_dirs}"

            if not search_dir.exists():
                return f"错误：目录不存在 - {search_path}"

            if not search_dir.is_dir():
                return f"错误：指定路径不是目录 - {search_path}"

            # 使用 pathlib 的 glob 方法进行匹配
            matches = list(search_dir.glob(pattern))

            # 按修改时间排序（最近的在前）
            def get_mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0.0

            matches.sort(key=get_mtime, reverse=True)

            # 构建结果
            files = []
            dirs = []
            for match in matches:
                try:
                    rel_path = str(match.relative_to(search_dir))
                    abs_path = str(match)
                    if match.is_file():
                        files.append({
                            "path": abs_path,
                            "relative_path": rel_path,
                            "name": match.name,
                            "size": match.stat().st_size,
                        })
                    elif match.is_dir():
                        dirs.append({
                            "path": abs_path,
                            "relative_path": rel_path,
                            "name": match.name,
                        })
                except OSError:
                    continue

            result = {
                "success": True,
                "pattern": pattern,
                "search_directory": str(search_dir),
                "matches": [f["relative_path"] for f in files] + [d["relative_path"] + "/" for d in dirs],
                "files": files,
                "directories": dirs,
                "file_count": len(files),
                "directory_count": len(dirs),
                "total_count": len(files) + len(dirs),
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


def create_glob_tool(safe_dirs: list[str]) -> GlobTool:
    """创建 Glob 工具"""
    return GlobTool(safe_dirs)
