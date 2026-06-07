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

import threading

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.text import Text

from config import constants


custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "red bold",
        "success": "green",
    }
)

# 全局Console单例
_console_instance: Console|None = None
_bus_lock = threading.Lock()


def _print_welcome(console: Console):
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                f"[bold cyan]{constants.LOGO_STR} {constants.NAME_EN}[/bold cyan] — {constants.NAME_CN}\n\n"
                f"[dim]{constants.DESCRIPTION}[/dim]"
            ),
            border_style="cyan",
            padding=(1, 6),
        )
    )
    console.print()


def get_console() -> Console:
    """
    获取全局Console单例
    """
    global _console_instance
    if _console_instance is None:
        with _bus_lock:
            if _console_instance is None:
                _console_instance = Console(theme=custom_theme)
                _print_welcome(_console_instance)
    return _console_instance
