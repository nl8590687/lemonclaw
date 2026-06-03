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
执行 bash/cmd 命令的工具
"""
import subprocess
import sys
import os
import signal
from typing import Type, Optional
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class BashToolInput(BaseModel):
    """执行 bash/cmd 命令工具的输入"""
    command: str = Field(description="要执行的 shell/cmd 命令")
    timeout: Optional[int] = Field(
        default=120,
        description="命令执行超时时间，单位秒，默认120秒"
    )


class BashTool(BaseTool):
    """执行 shell/cmd 命令的工具"""

    name: str = "bash_cmd"
    description: str = "执行任意 shell/cmd 命令，返回命令执行结果（stdout 和 stderr）"
    args_schema: Type[BaseModel] = BashToolInput

    def _run(self, command: str, timeout: int = 120, *args, **kwargs) -> str:
        """执行命令"""
        process = None
        try:
            popen_kwargs = {
                "text": True,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "encoding": "utf-8",
                "errors": "ignore",
            }

            if sys.platform.startswith("win"):
                popen_kwargs["shell"] = True
            else:
                # Unix: 使用新会话，让子进程拥有独立进程组
                # 防止 killpg 时误杀父进程
                popen_kwargs["shell"] = True
                popen_kwargs["executable"] = "/bin/bash"
                popen_kwargs["start_new_session"] = True

            process = subprocess.Popen(command, **popen_kwargs)

            # 等待进程完成，设置超时
            stdout, stderr = process.communicate(timeout=timeout)

            # 构建输出
            output = []
            if stdout:
                output.append("标准输出:\n" + stdout)
            if stderr:
                output.append("标准错误:\n" + stderr)
            output.append(f"退出代码: {process.returncode}")

            return "\n\n".join(output)

        except subprocess.TimeoutExpired:
            if process:
                self._kill_process(process)
            return f"命令执行超时({timeout}秒): {command}"

        except Exception as e:
            if process and process.poll() is None:
                self._kill_process(process)
            return f"执行命令时出错: {str(e)}"

    def _kill_process(self, process: subprocess.Popen) -> None:
        """
        安全终止子进程及其子进程树，不影响父进程

        Args:
            process: 要终止的子进程
        """
        try:
            if sys.platform.startswith("win"):
                # Windows: 使用 taskkill 终止进程树
                subprocess.run(
                    f"taskkill /F /T /PID {process.pid}",
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
            else:
                # Unix: 进程已在独立会话中（start_new_session=True），
                # 安全地终止整个进程组
                try:
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    # 给进程 3 秒优雅退出
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(pgid, signal.SIGKILL)
                        process.wait(timeout=3)
                except (ProcessLookupError, PermissionError):
                    # 进程组已不存在或无权限，直接尝试终止进程
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
        except Exception:
            # 最终兜底：直接终止
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass


def create_bash_tool() -> BashTool:
    """创建 bash 工具"""
    return BashTool()
