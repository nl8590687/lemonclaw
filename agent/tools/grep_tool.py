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

"""Grep 工具 - 在文件内容中搜索特定模式"""
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Type
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# 默认跳过的目录名
DEFAULT_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode",
}

# 默认跳过的文件扩展名（二进制文件等）
DEFAULT_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".obj",
    ".o", ".a", ".lib", ".png", ".jpg", ".jpeg", ".gif",
    ".bmp", ".ico", ".webp", ".mp3", ".mp4", ".avi", ".mov",
    ".wav", ".zip", ".tar", ".gz", ".rar", ".7z", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".woff", ".woff2", ".ttf", ".eot", ".class", ".jar",
    ".war", ".sqlite", ".db",
}

# 文件扩展名到语言类型的映射
EXTENSION_MAP = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "java": "java",
    "go": "go",
    "rs": "rust",
    "c": "c",
    "cpp": "cpp",
    "h": "c",
    "hpp": "cpp",
    "cs": "csharp",
    "rb": "ruby",
    "php": "php",
    "swift": "swift",
    "kt": "kotlin",
    "scala": "scala",
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
    "ps1": "powershell",
    "bat": "batch",
    "cmd": "batch",
    "sql": "sql",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "less": "less",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "xml": "xml",
    "md": "markdown",
    "rst": "rst",
    "lua": "lua",
    "r": "r",
    "m": "objc",
    "dart": "dart",
}


def _get_language_type(file_path: Path) -> Optional[str]:
    """根据文件扩展名判断语言类型"""
    ext = file_path.suffix.lstrip(".")
    return EXTENSION_MAP.get(ext)


def _is_text_file(file_path: Path) -> bool:
    """判断是否为可搜索的文本文件"""
    if file_path.suffix.lower() in DEFAULT_SKIP_EXTENSIONS:
        return False
    # 无扩展名的文件也尝试搜索（小文件）
    return True


class GrepToolInput(BaseModel):
    """Grep 工具的输入"""
    pattern: str = Field(
        description="要搜索的正则表达式模式或普通字符串"
    )
    path: Optional[str] = Field(
        default=None,
        description="搜索的根目录路径，默认为当前工作目录"
    )
    glob: Optional[str] = Field(
        default=None,
        description="文件名过滤模式（如 '*.py'、'*.{js,ts}'），仅搜索匹配的文件"
    )
    type: Optional[str] = Field(
        default=None,
        description="按语言类型过滤文件（如 python、javascript、go、rust、java 等）"
    )
    case_insensitive: bool = Field(
        default=False,
        description="是否忽略大小写，默认 False"
    )
    context: Optional[int] = Field(
        default=None,
        description="显示匹配行的上下文行数（前后各N行），默认不显示上下文"
    )
    head_limit: Optional[int] = Field(
        default=None,
        description="限制返回的最大匹配数，默认不限制"
    )
    invert_match: bool = Field(
        default=False,
        description="反向匹配，返回不包含模式的行，默认 False"
    )


class GrepTool(BaseTool):
    """文件内容搜索工具 - 在文件内容中搜索特定模式"""

    name: str = "grep"
    description: str = (
        "在文件内容中搜索特定模式（字符串或正则表达式），是代码库探索的核心工具。"
        "支持递归搜索目录、忽略大小写、显示上下文行、按文件类型过滤、反向匹配等。"
        "典型场景：重构前搜索函数使用位置、调试时查找错误信息、搜索变量定义和使用、"
        "安全检查硬编码密钥、全局替换前确认修改范围。"
    )
    args_schema: Type[BaseModel] = GrepToolInput

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

    def _should_skip_dir(self, dir_name: str) -> bool:
        """判断是否应跳过该目录"""
        return dir_name in DEFAULT_SKIP_DIRS

    def _should_search_file(self, file_path: Path, glob_pattern: Optional[str], type_filter: Optional[str]) -> bool:
        """判断是否应搜索该文件"""
        # 检查文件扩展名
        if not _is_text_file(file_path):
            return False

        # 按语言类型过滤
        if type_filter:
            lang = _get_language_type(file_path)
            if lang != type_filter.lower():
                return False

        # 按 glob 模式过滤
        if glob_pattern:
            # 支持逗号分隔的多模式，如 "*.{py,js}" 需要转换为多个 glob
            if "," in glob_pattern:
                patterns = [p.strip().strip("{}") for p in glob_pattern.strip("{}").split(",")]
                if not any(file_path.match(p) for p in patterns):
                    return False
            else:
                if not file_path.match(glob_pattern):
                    return False

        return True

    def _search_file(self, file_path: Path, regex: re.Pattern, context_lines: Optional[int],
                     invert: bool, head_limit: Optional[int], total_count: int) -> tuple:
        """
        在单个文件中搜索模式

        Returns:
            tuple: (matches, total_count) 其中 matches 是匹配结果列表，total_count 是累计匹配总数
        """
        matches = []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except (OSError, PermissionError):
            return matches, total_count

        for line_num, line in enumerate(lines, start=1):
            line_stripped = line.rstrip("\n\r")
            matched = bool(regex.search(line_stripped))

            if invert:
                matched = not matched

            if matched:
                if total_count >= (head_limit or float("inf")):
                    return matches, total_count

                match_entry = {
                    "file": str(file_path),
                    "line_number": line_num,
                    "content": line_stripped,
                }

                # 添加上下文行
                if context_lines and context_lines > 0:
                    before = []
                    for i in range(max(0, line_num - 1 - context_lines), line_num - 1):
                        before.append({
                            "line_number": i + 1,
                            "content": lines[i].rstrip("\n\r"),
                        })
                    after = []
                    for i in range(line_num, min(len(lines), line_num - 1 + context_lines + 1)):
                        after.append({
                            "line_number": i + 1,
                            "content": lines[i].rstrip("\n\r"),
                        })
                    match_entry["before"] = before
                    match_entry["after"] = after

                matches.append(match_entry)
                total_count += 1

        return matches, total_count

    def _run(self, *args, **kwargs) -> str:
        pattern: Optional[str] = None
        search_path: Optional[str] = None
        glob_filter: Optional[str] = None
        type_filter: Optional[str] = None
        case_insensitive: bool = False
        context_lines: Optional[int] = None
        head_limit: Optional[int] = None
        invert_match: bool = False

        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        pattern = parsed.get("pattern")
                        search_path = parsed.get("path")
                        glob_filter = parsed.get("glob")
                        type_filter = parsed.get("type")
                        case_insensitive = parsed.get("case_insensitive", False)
                        context_lines = parsed.get("context")
                        head_limit = parsed.get("head_limit")
                        invert_match = parsed.get("invert_match", False)
                except Exception:
                    pattern = first_arg
            elif isinstance(first_arg, dict):
                pattern = first_arg.get("pattern")
                search_path = first_arg.get("path")
                glob_filter = first_arg.get("glob")
                type_filter = first_arg.get("type")
                case_insensitive = first_arg.get("case_insensitive", False)
                context_lines = first_arg.get("context")
                head_limit = first_arg.get("head_limit")
                invert_match = first_arg.get("invert_match", False)

        # 从 kwargs 补充
        if not pattern:
            pattern = kwargs.get("pattern")
        if not search_path:
            search_path = kwargs.get("path")
        if not glob_filter:
            glob_filter = kwargs.get("glob")
        if not type_filter:
            type_filter = kwargs.get("type")
        if "case_insensitive" in kwargs:
            case_insensitive = kwargs["case_insensitive"]
        if context_lines is None:
            context_lines = kwargs.get("context")
        if head_limit is None:
            head_limit = kwargs.get("head_limit")
        if "invert_match" in kwargs:
            invert_match = kwargs["invert_match"]

        if not pattern:
            return "错误：必须提供 pattern 参数指定搜索模式"

        if not search_path:
            search_path = "."

        if not self._safe_dirs:
            return "错误：未配置安全目录列表"

        try:
            search_dir = Path(search_path).resolve()

            if not self._is_path_safe(str(search_dir)):
                return f"错误：路径不在允许的安全目录列表中。安全目录前缀: {self._safe_dirs}"

            if not search_dir.exists():
                return f"错误：路径不存在 - {search_path}"

            # 如果搜索路径是单个文件，直接搜索该文件
            if search_dir.is_file():
                if not self._is_path_safe(str(search_dir)):
                    return f"错误：文件不在允许的安全目录列表中"
                search_dir_path = search_dir
                search_dir = search_dir.parent
            else:
                search_dir_path = None

            # 编译正则表达式
            flags = re.MULTILINE
            if case_insensitive:
                flags |= re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return f"错误：无效的正则表达式 - {str(e)}"

            all_matches: List[Dict] = []
            files_with_matches: List[str] = []
            total_count = 0
            truncated = False

            # 搜索文件
            if search_dir_path and search_dir_path.is_file():
                # 搜索单个文件
                if self._should_search_file(search_dir_path, glob_filter, type_filter):
                    file_matches, total_count = self._search_file(
                        search_dir_path, regex, context_lines, invert_match, head_limit, total_count
                    )
                    if file_matches:
                        all_matches.extend(file_matches)
                        files_with_matches.append(str(search_dir_path))
            else:
                # 递归搜索目录
                for root, dirs, files in os.walk(search_dir):
                    # 跳过不需要搜索的目录（原地修改 dirs 影响 os.walk 遍历）
                    dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]

                    for filename in files:
                        if head_limit and total_count >= head_limit:
                            truncated = True
                            break

                        file_path = Path(root) / filename

                        if not self._should_search_file(file_path, glob_filter, type_filter):
                            continue

                        file_matches, total_count = self._search_file(
                            file_path, regex, context_lines, invert_match, head_limit, total_count
                        )
                        if file_matches:
                            all_matches.extend(file_matches)
                            if str(file_path) not in files_with_matches:
                                files_with_matches.append(str(file_path))

                    if truncated:
                        break

            # 统计每个文件的匹配数
            file_counts: Dict[str, int] = {}
            for m in all_matches:
                f = m["file"]
                file_counts[f] = file_counts.get(f, 0) + 1

            result = {
                "success": True,
                "pattern": pattern,
                "search_directory": str(search_dir),
                "case_insensitive": case_insensitive,
                "total_matches": total_count,
                "files_with_matches": len(files_with_matches),
                "file_counts": file_counts,
                "files": files_with_matches,
                "matches": all_matches,
            }

            if truncated:
                result["truncated"] = True
                result["message"] = f"结果已截断，仅显示前 {head_limit} 条匹配。可使用 head_limit 参数调整或缩小搜索范围。"

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


def create_grep_tool(safe_dirs: list[str]) -> GrepTool:
    """创建 Grep 工具"""
    return GrepTool(safe_dirs)
