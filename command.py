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

from rich.table import Table

from agent.agent import AgentService
from channels.out.stdout import BaseOutChannel


def _print_help(out_chan: BaseOutChannel):
    table = Table(title="可用命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/quit, /exit, /q", "退出程序")
    table.add_row("/clear", "清空对话历史")
    table.add_row("/tokens", "查看累计 Token 用量")
    table.add_row("/help", "显示本帮助")
    table.add_row("")
    table.add_row("[bold cyan]核心记忆[/]", "")
    table.add_row("/memory", "查看当前核心记忆")
    table.add_row("/remember <key> <value>", "记住某事（fact 类型）")
    table.add_row("/remember <type>:<key> <value>", "记住某事，指定类型")
    table.add_row("/forget <type>:<key>", "删除某条记忆")
    table.add_row("")
    table.add_row("[bold cyan]历史会话[/]", "")
    table.add_row("/sessions", "列出最近会话")
    table.add_row("/load <id>", "查看某会话的历史")
    table.add_row("")
    table.add_row("[bold cyan]长期记忆块[/]", "")
    table.add_row("/chunks", "列出所有长期记忆块")
    table.add_row("/addchunk <type> <title> <content>", "添加记忆块")
    table.add_row("/delchunk <id>", "删除记忆块")
    table.add_row("/search <query>", "搜索相关记忆")
    table.add_row("")
    table.add_row("[bold cyan]Skill 管理[/]", "")
    table.add_row("/skills", "列出所有可用技能")
    table.add_row("/skills refresh", "刷新技能索引（新增/修改后）")

    out_chan.write_menu_content(table)


def _deal_clear(out_chan: BaseOutChannel, agent_service: AgentService):
    agent_service.reset_session()
    out_chan.write_menu_content("[success]对话已清空！[/success]\n")


def _print_total_tokens(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def _print_memory(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def _handle_remember(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _handle_forget(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _print_sessions(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def _handle_load_session(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _print_chunks(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def _handle_add_chunk(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _handle_del_chunk(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _handle_search(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    pass


def _print_skills(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def _refresh_skills(out_chan: BaseOutChannel, agent_service: AgentService):
    pass


def handle_command(out_chan: BaseOutChannel, agent_service: AgentService, command: str) -> bool:
    """处理 / 命令，返回是否继续对话"""
    cmd = command.lower().strip()

    if cmd in ("/quit", "/exit", "/q"):
        return False

    if cmd == "/help":
        _print_help(out_chan)
        return True

    if cmd == "/clear":
        _deal_clear(out_chan, agent_service)
        return True

    if cmd == "/tokens":
        _print_total_tokens(out_chan, agent_service)
        return True

    # 记忆系统命令
    if cmd == "/memory":
        _print_memory(out_chan, agent_service)
        return True

    if cmd.startswith("/remember "):
        _handle_remember(out_chan, agent_service, command)
        return True

    if cmd.startswith("/forget "):
        _handle_forget(out_chan, agent_service, command)
        return True

    if cmd == "/sessions":
        _print_sessions(out_chan, agent_service)
        return True

    if cmd.startswith("/load "):
        _handle_load_session(out_chan, agent_service, command)
        return True

    # 长期记忆块命令
    if cmd == "/chunks":
        _print_chunks(out_chan, agent_service)
        return True

    if cmd.startswith("/addchunk "):
        _handle_add_chunk(out_chan, agent_service, command)
        return True

    if cmd.startswith("/delchunk "):
        _handle_del_chunk(out_chan, agent_service, command)
        return True

    if cmd.startswith("/search "):
        _handle_search(out_chan, agent_service, command)
        return True

    # ============ Skill 命令 ============
    if cmd == "/skills":
        _print_skills(out_chan, agent_service)
        return True

    if cmd == "/skills refresh":
        _refresh_skills(out_chan, agent_service)
        return True

    out_chan.write_menu_content(f"[warning]未知命令: {command}[/warning]\n输入 [bold]/help[/] 查看可用命令\n")
    return True
