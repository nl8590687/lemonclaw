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

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from channels.out.base import BaseOutChannel
from config import constants

custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "red bold",
        "success": "green",
    }
)


class TerminalOutputChannel(BaseOutChannel):
    """
    终端输出通道
    """
    def __init__(self):
        super().__init__()
        self.console = Console(theme=custom_theme)
        self._print_welcome()

    def _print_welcome(self):
        self.console.print()
        self.console.print(
            Panel(
                Text.from_markup(
                    f"[bold cyan]{constants.LOGO_STR} {constants.NAME_EN}[/bold cyan] — {constants.NAME_CN}\n\n"
                    f"[dim]{constants.DESCRIPTION}[/dim]"
                ),
                border_style="cyan",
                padding=(1, 6),
            )
        )
        self.console.print()

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

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="dim")
        table.add_column(style="cyan")
        table.add_column(style="dim")
        table.add_column(style="cyan")

        table.add_row(
            "本轮消耗:",
            f"输入 {context.get("tokens", {}).get('prompt_tokens', 0)} / "
            f"输出 {context.get("tokens", {}).get('completion_tokens', 0)} / "
            f"总计 {context.get("tokens", {}).get('total_tokens', 0)} tokens",
        )
        table.add_row(
            "会话累计:",
            f"输入 {context.get("context_tokens", {}).get('total_prompt_tokens', 0)} / "
            f"输出 {context.get("context_tokens", {}).get('total_completion_tokens', 0)} / "
            f"总计 {context.get("context_tokens", {}).get('context_total_tokens', 0)} tokens",
        )

        # 更详细的消息统计
        msg_detail = (
            f"{context.get("messages", {}).get('memory_tokens', 0)} tokens - "
            f"[bold]{context.get("messages", {}).get('human_count', 0)}[/] 用户 / "
            f"[bold]{context.get("messages", {}).get('ai_count', 0)}[/] AI / "
            f"[bold]{context.get("messages", {}).get('tool_count', 0)}[/] 工具 / "
            f"[bold]{context.get("messages", {}).get('system_count', 0)}[/] 系统 "
            f"([bold]{context.get("messages", {}).get('message_count', 0)}[/] 总消息)"
        )
        table.add_row("上下文记忆:", msg_detail)

        self.console.print(table)
        self.console.print()
