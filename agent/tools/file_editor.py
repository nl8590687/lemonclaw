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
文件编辑工具 - 支持读取和写入文本文件
"""
import os
import json
import difflib
from pathlib import Path
from typing import Optional, Type, List
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class ReadFileInput(BaseModel):
    """读取文件工具的输入"""
    path: str = Field(description="要读取的文件路径（支持相对路径）")


class WriteFileInput(BaseModel):
    """写入文件工具的输入"""
    path: str = Field(description="要写入的文件路径（支持相对路径）")
    content: Optional[str] = Field(default=None, description="要写入的新内容")
    new_content: Optional[str] = Field(default=None, description="要写入的新内容（别名）")
    old_content: Optional[str] = Field(default=None, description="原文件内容，用于乐观锁校验。新文件可留空。")


class ReadFileTool(BaseTool):
    """读取文件工具"""

    name: str = "read_file"
    description: str = "读取指定路径的文本文件内容。支持代码文件、markdown、yaml 等各种文本格式。"
    args_schema: Type[BaseModel] = ReadFileInput

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
        检查路径是否安全，防止路径穿越和符号链接攻击

        Args:
            target_path: 要检查的目标路径

        Returns:
            bool: 路径是否安全
        """
        if not self._safe_dirs:
            return False

        try:
            target_path_obj = Path(target_path)

            # 检查是否是符号链接（无论是否存在都要检查）
            if target_path_obj.is_symlink() or os.path.islink(str(target_path_obj)):
                return False

            # 解析为绝对路径
            target_abs = target_path_obj.resolve()

            # 再次检查解析后的路径是否是符号链接
            if target_abs.is_symlink() or os.path.islink(str(target_abs)):
                return False

            # 检查路径是否在安全目录内
            for safe_dir in self._safe_dirs:
                safe_abs = Path(safe_dir).resolve()

                # 使用 commonpath 检查路径是否在安全目录下
                try:
                    common = os.path.commonpath([str(safe_abs), str(target_abs)])
                    if str(common) == str(safe_abs):
                        return True
                except ValueError:
                    continue

            return False
        except Exception:
            return False

    def _run(self, *args, **kwargs) -> str:
        """
        读取文件内容

        Returns:
            str: 文件内容或错误信息
        """
        # 解析参数
        path: Optional[str] = None

        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                # 尝试解析 JSON
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        path = parsed.get("path")
                except Exception:
                    path = first_arg
            elif isinstance(first_arg, dict):
                path = first_arg.get("path")

        if not path:
            path = kwargs.get("path")

        if not path:
            return "错误：必须提供文件路径参数 path"

        if not self._safe_dirs:
            return "错误：未配置安全目录列表"

        try:
            target_file = Path(path).resolve()

            if not self._is_path_safe(str(target_file)):
                return f"错误：路径不在允许的安全目录列表中。安全目录前缀: {self._safe_dirs}"

            if not target_file.exists():
                return f"错误：文件不存在 - {path}"

            if not target_file.is_file():
                return f"错误：指定路径不是文件 - {path}"

            # 读取文件内容
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read()

            result = {
                "success": True,
                "path": str(target_file),
                "content": content
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


class WriteFileTool(BaseTool):
    """写入文件工具 - 带乐观锁"""

    name: str = "write_file"
    description: str = "写入文本文件内容。使用参数 content 指定新内容。必须先读取文件获取 old_content 用于乐观锁校验。如果文件不存在，old_content 留空即可创建新文件。"
    args_schema: Type[BaseModel] = WriteFileInput

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
        检查路径是否安全，防止路径穿越和符号链接攻击

        Args:
            target_path: 要检查的目标路径

        Returns:
            bool: 路径是否安全
        """
        if not self._safe_dirs:
            return False

        try:
            target_path_obj = Path(target_path)

            # 检查是否是符号链接（无论是否存在都要检查）
            if target_path_obj.is_symlink() or os.path.islink(str(target_path_obj)):
                return False

            # 解析为绝对路径
            target_abs = target_path_obj.resolve()

            # 再次检查解析后的路径是否是符号链接
            if target_abs.is_symlink() or os.path.islink(str(target_abs)):
                return False

            # 检查路径是否在安全目录内
            for safe_dir in self._safe_dirs:
                safe_abs = Path(safe_dir).resolve()

                # 使用 commonpath 检查路径是否在安全目录下
                try:
                    common = os.path.commonpath([str(safe_abs), str(target_abs)])
                    if str(common) == str(safe_abs):
                        return True
                except ValueError:
                    continue

            return False
        except Exception:
            return False

    def _show_diff(self, old_content: str, new_content: str) -> None:
        """
        显示文件内容差异（带行号）

        Args:
            old_content: 原内容
            new_content: 新内容
        """
        print("\n" + "="*80)
        print("文件变更差异:")
        print("="*80)

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        differ = difflib.Differ()
        diff_result = list(differ.compare(old_lines, new_lines))

        if not diff_result or all(line.startswith("  ") for line in diff_result):
            print("(内容未发生变化)")
            print("="*80 + "\n")
            return

        old_line_num = 0
        new_line_num = 0

        for line in diff_result:
            # 移除行尾换行符用于显示
            display_line = line.rstrip("\r\n")

            if line.startswith("  "):
                # 未变化的行
                old_line_num += 1
                new_line_num += 1
                print(f"{old_line_num:4d} {new_line_num:4d}   {display_line}")
            elif line.startswith("- "):
                # 删除的行
                old_line_num += 1
                print(f"{old_line_num:4d}        \033[1;31m- {display_line[2:]}\033[0m")
            elif line.startswith("+ "):
                # 新增的行
                new_line_num += 1
                print(f"        {new_line_num:4d} \033[1;32m+ {display_line[2:]}\033[0m")
            elif line.startswith("? "):
                # 提示行
                print(f"              \033[1;33m{display_line}\033[0m")

        print("="*80 + "\n")

    def _run(self, *args, **kwargs) -> str:
        """
        写入文件内容

        Returns:
            str: 结果信息
        """
        # 解析参数
        path: Optional[str] = None
        content: str = ""
        old_content: Optional[str] = None

        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                # 尝试解析 JSON
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        path = parsed.get("path")
                        content = parsed.get("content") or parsed.get("new_content", "")
                        old_content = parsed.get("old_content")
                except Exception:
                    pass
            elif isinstance(first_arg, dict):
                path = first_arg.get("path")
                content = first_arg.get("content") or first_arg.get("new_content", "")
                old_content = first_arg.get("old_content")

        if not path:
            path = kwargs.get("path")
        if not content:
            content = kwargs.get("content") or kwargs.get("new_content", "")
        if old_content is None:
            old_content = kwargs.get("old_content")

        if not path:
            return "错误：必须提供文件路径参数 path"

        if content is None:
            return "错误：必须提供文件内容参数 content"

        if not self._safe_dirs:
            return "错误：未配置安全目录列表"

        try:
            target_file = Path(path).resolve()

            if not self._is_path_safe(str(target_file)):
                return f"错误：路径不在允许的安全目录列表中。安全目录前缀: {self._safe_dirs}"

            # 确保目录存在
            target_file.parent.mkdir(parents=True, exist_ok=True)

            # 检查文件是否存在
            file_exists = target_file.exists()

            if file_exists:
                # 读取当前文件内容进行校验
                current_content = ""
                with open(target_file, "r", encoding="utf-8") as f:
                    current_content = f.read()

                # 乐观锁校验
                if old_content is None:
                    return "错误：修改已有文件必须提供 old_content 参数（先通过 read_file 读取）"

                if current_content != old_content:
                    return "错误：写入失败，文件已被外部编辑。请重新读取文件后再尝试修改。"

                # 显示差异
                self._show_diff(old_content, content)

                # 写入新内容
                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(content)

                result = {
                    "success": True,
                    "path": str(target_file),
                    "action": "modified",
                    "message": "文件已更新"
                }
            else:
                # 创建新文件
                if old_content is not None and old_content != "":
                    return "错误：创建新文件时 old_content 应该为空"

                # 显示差异（从空到新内容）
                self._show_diff("", content)

                with open(target_file, "w", encoding="utf-8") as f:
                    f.write(content)

                result = {
                    "success": True,
                    "path": str(target_file),
                    "action": "created",
                    "message": "新文件已创建"
                }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


def create_read_file_tool(safe_dirs: list[str]) -> ReadFileTool:
    """
    创建读取文件工具
    """
    return ReadFileTool(safe_dirs)


def create_write_file_tool(safe_dirs: list[str]) -> WriteFileTool:
    """
    创建写入文件工具
    """
    return WriteFileTool(safe_dirs)
