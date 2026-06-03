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
Git 工具 - 安全的 git 命令封装，只允许白名单操作
"""

import json
import subprocess
from pathlib import Path
from typing import Optional, Set, ClassVar
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class GitToolInput(BaseModel):
    command: str = Field(description="Git 子命令，仅支持：diff, status, log, branch, show, ls-files, remote, blame, stash")
    args: Optional[str] = Field(default="", description="命令附加参数，如 'file.txt' 或 '-n 10'")


class GitTool(BaseTool):
    """
    Git 工具 - 只允许白名单内的 git 命令
    """

    name: str = "git_tool"
    description: str = "执行 git 只读命令。支持：diff, status, log, branch, show, ls-files, remote, blame, stash"
    args_schema: type[BaseModel] = GitToolInput

    # 允许的 git 子命令白名单
    ALLOWED_COMMANDS: ClassVar[Set[str]] = {"diff", "status", "log", "branch", "show", "ls-files", "remote", "blame", "stash"}

    # 使用 model_config 允许额外字段
    model_config = {"extra": "allow"}

    def _run(self, *args, **kwargs) -> str:
        """执行 git 命令 - 完全手动解析参数"""
        # 解析参数
        command: Optional[str] = None
        args_str: Optional[str] = None

        # 方式0: 先检查是否有列表参数 ["diff", "file.txt"]
        if args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, list) and len(first_arg) >= 1:
                command = first_arg[0]
                if len(first_arg) >= 2:
                    # 如果是列表的第二个元素，用空格连接后面所有
                    args_str = " ".join(str(x) for x in first_arg[1:])

        # 方式1: 尝试从 args 解析 JSON
        if not command and args and len(args) > 0:
            first_arg = args[0]
            if isinstance(first_arg, str):
                try:
                    parsed = json.loads(first_arg)
                    if isinstance(parsed, dict):
                        command = parsed.get("command")
                        args_str = parsed.get("args")
                    elif isinstance(parsed, list) and len(parsed) >= 1:
                        # JSON 也是列表格式
                        command = parsed[0]
                        if len(parsed) >= 2:
                            args_str = " ".join(str(x) for x in parsed[1:])
                except Exception:
                    # 如果不是 JSON，可能是直接传的 command
                    if len(args) == 1:
                        command = first_arg
                    elif len(args) >= 2:
                        command = first_arg
                        args_str = args[1]
            elif isinstance(first_arg, dict):
                command = first_arg.get("command")
                args_str = first_arg.get("args")

        # 方式2: 从 kwargs 获取
        if not command:
            command = kwargs.get("command")
        if args_str is None:
            args_str = kwargs.get("args", "")

        # 方式2.5: 检查 kwargs 有没有传入列表
        if not command:
            for key, value in kwargs.items():
                if isinstance(value, list) and len(value) >= 1:
                    command = value[0]
                    if len(value) >= 2:
                        args_str = " ".join(str(x) for x in value[1:])
                    break

        # 方式3: 特殊兼容 - 检查 command 是否嵌套了 JSON
        if command and isinstance(command, str) and command.startswith('{') and command.endswith('}'):
            try:
                parsed = json.loads(command)
                if isinstance(parsed, dict):
                    command = parsed.get("command", command)
                    if args_str is None:
                        args_str = parsed.get("args", "")
                elif isinstance(parsed, list) and len(parsed) >= 1:
                    command = parsed[0]
                    if len(parsed) >= 2:
                        args_str = " ".join(str(x) for x in parsed[1:])
            except Exception:
                pass

        # 方式4: 最鲁棒 - 如果 command 看起来像带引号和逗号的 "diff", "file.txt"
        if command and isinstance(command, str) and not args_str and ('", "' in command or "', '" in command):
            # 尝试解析这种格式
            import re
            # 用正则提取带引号的部分
            quoted_parts = re.findall(r'"([^"]+)"|\'([^\']+)\'', command)
            # 提取结果是 [('diff', ''), ('', 'file.txt')] 这种，需要扁平化
            parts = []
            for a, b in quoted_parts:
                parts.append(a or b)
            if len(parts) >= 1:
                command = parts[0]
                if len(parts) >= 2:
                    args_str = " ".join(parts[1:])

        # 方式5: 如果 command 包含逗号且不在白名单里，尝试简单逗号分割
        if command and isinstance(command, str) and ',' in command and command not in self.ALLOWED_COMMANDS:
            parts = [p.strip().strip('\'"') for p in command.split(',', 1)]
            if len(parts) >= 1 and parts[0] in self.ALLOWED_COMMANDS:
                command = parts[0]
                if len(parts) >= 2:
                    args_str = parts[1]

        # 验证 command
        if not command:
            return "错误：必须提供 git 命令参数。例如：git_tool(\"status\") 或 git_tool(\"diff\", \"file.txt\")"

        if command not in self.ALLOWED_COMMANDS:
            return f"错误：不支持的 git 命令 '{command}'。仅支持：{', '.join(sorted(self.ALLOWED_COMMANDS))}"

        try:
            # 构建完整命令
            cmd_parts = ["git", command]

            # 如果有额外参数，按空格分割（注意：简单分割，不处理引号等复杂情况）
            if args_str and isinstance(args_str, str) and args_str.strip():
                # 简单的空格分割
                cmd_parts.extend(args_str.strip().split())

            # 执行命令
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                cwd=Path.cwd()
            )

            # 构建返回结果
            output = {
                "success": result.returncode == 0,
                "command": " ".join(cmd_parts),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

            return json.dumps(output, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"错误：执行 git 命令失败 - {str(e)}"


def create_git_tool() -> GitTool:
    """创建 git 工具"""
    return GitTool()
