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

"""增量文件编辑工具 - 支持精确的单行/块替换，类似 Claude Code 的 Edit 功能"""

import json
import difflib
from pathlib import Path
from typing import Any, Dict, Optional, Type, List, Tuple
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class EditFileInput(BaseModel):
    path: str = Field(description="要编辑的文件路径")
    old_string: str = Field(description="要替换的原文本，必须与文件内容完全一致")
    new_string: str = Field(description="替换后的新文本")
    replace_all: bool = Field(default=False, description="是否替换所有匹配（多处匹配时使用）")


class EditFileTool(BaseTool):
    """增量文件编辑工具 - 支持精确的文本块替换"""

    name: str = "edit_file"
    description: str = "精确编辑文件：使用 old_string 和 new_string 进行精确匹配替换。old_string 必须与文件中的内容完全一致（包括缩进、换行符）。建议先读取文件确认内容。"
    args_schema: type[BaseModel] = EditFileInput

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
        """检查路径是否安全"""
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

    def _show_diff(self, old_content: str, new_content: str, filepath: str) -> None:
        """显示文件内容差异（带行号和颜色）"""
        print("\n" + "="*80)
        print(f"文件变更: {filepath}")
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
            display_line = line.rstrip("\r\n")

            if line.startswith("  "):
                old_line_num += 1
                new_line_num += 1
                print(f"{old_line_num:4d} {new_line_num:4d}   {display_line}")
            elif line.startswith("- "):
                old_line_num += 1
                print(f"{old_line_num:4d}        \033[1;31m- {display_line[2:]}\033[0m")
            elif line.startswith("+ "):
                new_line_num += 1
                print(f"        {new_line_num:4d} \033[1;32m+ {display_line[2:]}\033[0m")
            elif line.startswith("? "):
                print(f"              \033[1;33m{display_line}\033[0m")

        print("="*80 + "\n")

    def _find_all_matches(self, content: str, search: str) -> List[Tuple[int, int]]:
        """找出所有匹配的位置"""
        matches = []
        start = 0
        while True:
            idx = content.find(search, start)
            if idx == -1:
                break
            matches.append((idx, idx + len(search)))
            start = idx + 1
        return matches

    def _get_line_number(self, content: str, pos: int) -> int:
        """计算位置对应的行号"""
        return content.count('\n', 0, pos) + 1

    def _run(self, *args, **kwargs) -> str:
        """执行增量编辑 - 完全手动解析参数，兼容各种调用方式"""
        # 解析参数
        path: Optional[str] = None
        old_string: Optional[str] = None
        new_string: Optional[str] = None
        replace_all: bool = False

        # 方式1: 先尝试从 args 解析 JSON（这是 Agent 常用的方式）
        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                # 尝试解析 JSON
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        path = parsed.get("path")
                        old_string = parsed.get("old_string")
                        new_string = parsed.get("new_string")
                        replace_all = parsed.get("replace_all", False)
                except Exception:
                    pass
            elif isinstance(first_arg, dict):
                path = first_arg.get("path")
                old_string = first_arg.get("old_string")
                new_string = first_arg.get("new_string")
                replace_all = first_arg.get("replace_all", False)

        # 方式2: 如果 args 没解析到，尝试从 kwargs 获取
        if not path:
            path = kwargs.get("path")
        if not old_string:
            old_string = kwargs.get("old_string")
        if new_string is None:
            new_string = kwargs.get("new_string")
        if not replace_all:
            replace_all = kwargs.get("replace_all", False)

        # 方式3: 特殊兼容 - 如果 path 本身看起来像 JSON，再试一次解析
        if path and isinstance(path, str) and path.startswith('{') and path.endswith('}'):
            try:
                parsed = json.loads(path)
                if isinstance(parsed, dict):
                    path = parsed.get("path", path)
                    if not old_string:
                        old_string = parsed.get("old_string")
                    if new_string is None:
                        new_string = parsed.get("new_string")
                    replace_all = parsed.get("replace_all", replace_all)
            except Exception:
                pass

        # 最终校验
        if not path:
            return "错误：必须提供文件路径参数 path"
        if not old_string:
            return "错误：必须提供 old_string 参数（要替换的原文本）"
        if new_string is None:
            return "错误：必须提供 new_string 参数（替换后的新文本）"

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

            # 读取当前文件内容
            with open(target_file, "r", encoding="utf-8") as f:
                current_content = f.read()

            # 查找匹配
            matches = self._find_all_matches(current_content, old_string)

            if not matches:
                # 尝试帮用户诊断问题
                if old_string.strip() not in current_content:
                    return f"错误：在文件中找不到 old_string。请确保 old_string 与文件内容完全匹配（包括缩进、换行符）。建议先使用 read_file 读取文件确认内容。"
                else:
                    return f"错误：old_string 内容存在，但空白字符/换行符不匹配。请精确复制文件内容。"

            if len(matches) > 1 and not replace_all:
                line_numbers = [self._get_line_number(current_content, m[0]) for m in matches]
                return f"错误：在文件中找到 {len(matches)} 处匹配（行 {line_numbers}）。请使用 replace_all=true 替换所有匹配，或提供更具体的 old_string 以唯一定位。"

            # 执行替换
            file_new_content = current_content
            if replace_all:
                file_new_content = file_new_content.replace(old_string, new_string)
                replaced_count = len(matches)
            else:
                file_new_content = file_new_content.replace(old_string, new_string, 1)
                replaced_count = 1

            # 显示差异
            self._show_diff(current_content, file_new_content, str(target_file))

            # 写入文件
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(file_new_content)

            result = {
                "success": True,
                "path": str(target_file),
                "action": "edited",
                "replacements": replaced_count,
                "message": f"成功替换 {replaced_count} 处"
            }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：{str(e)}"


def create_edit_file_tool(safe_dirs: list[str]) -> EditFileTool:
    """
    创建增量文件编辑工具
    """
    return EditFileTool(safe_dirs)
