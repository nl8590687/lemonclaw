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

from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from channels.device.console import get_console
from channels.out.base import BaseOutChannel


class TerminalOutputChannel(BaseOutChannel):
    """
    终端输出通道
    """
    def __init__(self):
        super().__init__()
        self.console = get_console()

    def write_message(self, msg: str, context: dict[str, object]):
        self.console.print()
        self.console.rule("[bold blue]助手", style="blue")
        self.console.print(Markdown(msg))
        self.console.print()

        self.console.rule(style="blue")
        self._display_token_stats(context)
        self.console.rule(style="blue")

    def print(self, msg: str):
        self.console.print(msg, end="", highlight=False)

    def write_tool_calling(self, tool_name: str, param_str: str):
        self.console.print()
        self.console.print(
            Text(f"▶ 执行工具: {tool_name} {param_str}", style="bold yellow")
        )

    def write_tool_result(self, output: object):
        output_str = str(output)
        if len(output_str) > 300:
            output_str = output_str[:300] + "..."
        self.console.print(Text(f"  结果: {output_str}", style="dim"))

    def write_tool_error(self, error: BaseException):
        self.console.print(Text(f"  工具错误: {error}", style="bold red"))

    def _display_token_stats(self, context: dict[str, object]):
        if not isinstance(context, dict):
            context = {}

        def section(name: str) -> dict[str, object]:
            value = context.get(name, {})
            return value if isinstance(value, dict) else {}

        tokens = section("tokens")
        context_tokens = section("context_tokens")
        messages = section("messages")

        prompt_tokens = tokens.get("prompt_tokens", 0)
        cached_prompt_tokens = tokens.get("cached_prompt_tokens", 0)
        uncached_prompt_tokens = tokens.get("uncached_prompt_tokens", prompt_tokens - cached_prompt_tokens)
        completion_tokens = tokens.get("completion_tokens", 0)
        total_tokens = tokens.get("total_tokens", 0)
        total_prompt_tokens = context_tokens.get("total_prompt_tokens", 0)
        total_cached_prompt_tokens = context_tokens.get("total_cached_prompt_tokens", 0)
        total_uncached_prompt_tokens = context_tokens.get(
            "total_uncached_prompt_tokens", total_prompt_tokens - total_cached_prompt_tokens)
        total_completion_tokens = context_tokens.get("total_completion_tokens", 0)
        context_total_tokens = context_tokens.get("context_total_tokens", 0)
        memory_tokens = messages.get("memory_tokens", 0)
        human_count = messages.get("human_count", 0)
        ai_count = messages.get("ai_count", 0)
        tool_count = messages.get("tool_count", 0)
        system_count = messages.get("system_count", 0)
        message_count = messages.get("message_count", 0)

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="cyan")
        table.add_column(style="dim")
        table.add_column(style="cyan")

        table.add_row(
            "本轮消耗:",
            f"输入 {prompt_tokens}（缓存 {cached_prompt_tokens} / 未缓存 {uncached_prompt_tokens}） / 输出 {completion_tokens} / 总计 {total_tokens} tokens",
        )
        table.add_row(
            "会话累计:",
            f"输入 {total_prompt_tokens}（缓存 {total_cached_prompt_tokens} / 未缓存 {total_uncached_prompt_tokens}） / 输出 {total_completion_tokens} / 总计 {context_total_tokens} tokens",
        )

        msg_detail = (
            f"{memory_tokens} tokens - "
            f"[bold]{human_count}[/] 用户 / "
            f"[bold]{ai_count}[/] AI / "
            f"[bold]{tool_count}[/] 工具 / "
            f"[bold]{system_count}[/] 系统 "
            f"([bold]{message_count}[/] 总消息)"
        )
        table.add_row("上下文记忆:", msg_detail)

        self.console.print(table)
        self.console.print()

    def write_menu_content(self, content: object):
        self.console.print(content)
        self.console.print()

    def write_system_error(self, content: str):
        self.console.print(f"[error]{content}[/]")
