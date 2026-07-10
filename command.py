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
from rich.panel import Panel

from agent.agent import AgentService
from channels.device.crontab import get_cron_manager, parse_cron, validate_cron
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
    table.add_row("")
    table.add_row("[bold cyan]定时任务[/]", "")
    table.add_row("/cron", "列出所有定时任务（/cron help 查看子命令）")
    table.add_row("/cron create <表达式> <提示词>", "创建定时任务")
    table.add_row("/cron delete <id>", "删除定时任务")
    table.add_row("/cron enable <id>", "启用定时任务")
    table.add_row("/cron disable <id>", "禁用定时任务")
    table.add_row("/cron show <id>", "查看任务详情")

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


# ============ Cron 定时任务命令 ============

def _cron_list(out_chan: BaseOutChannel):
    """列出所有定时任务"""
    manager = get_cron_manager()
    tasks = manager.list_tasks(include_disabled=True)

    if not tasks:
        out_chan.write_menu_content("[dim]当前没有定时任务[/dim]\n")
        return

    table = Table(title="Cron 定时任务", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("状态")
    table.add_column("执行计划")
    table.add_column("下次执行", style="dim")
    table.add_column("最后执行", style="dim")
    table.add_column("提示词(预览)")

    for task in tasks:
        status = "[green]✓启用[/]" if task.enabled else "[red]✗禁用[/]"
        try:
            next_run = parse_cron(task.cron_expression).next_run().strftime("%Y-%m-%d %H:%M")
        except Exception:
            next_run = "无效"
        last = task.last_run_at.strftime("%Y-%m-%d %H:%M") if task.last_run_at else "-"
        preview = task.prompt[:40] + ("..." if len(task.prompt) > 40 else "")
        table.add_row(task.task_id, status, task.cron_expression, next_run, last, preview)

    out_chan.write_menu_content(table)


def _cron_create(out_chan: BaseOutChannel, command: str):
    """创建定时任务: /cron create <cron表达式> <提示词>"""
    # 用 split(None, 2) 取出 "/cron" "create" 之后的完整内容，保留提示词原样大小写
    parts = command.split(None, 2)
    rest = parts[2].strip() if len(parts) > 2 else ""

    if not rest:
        out_chan.write_menu_content(
            "[warning]用法: /cron create <cron表达式> <提示词>[/warning]\n"
            "示例: /cron create 0 9 * * * 每天早上9点提醒我喝水\n"
            "      /cron create @daily 每天提醒我写日报\n"
        )
        return

    tokens = rest.split()
    # @daily / @hourly 等预设占 1 个 token；否则按 5 字段 cron 取前 5 个 token
    if tokens[0].startswith("@"):
        cron_expr = tokens[0]
        prompt = " ".join(tokens[1:])
    else:
        cron_expr = " ".join(tokens[:5])
        prompt = " ".join(tokens[5:])

    if not prompt:
        out_chan.write_menu_content("[warning]提示词不能为空[/warning]\n")
        return

    valid, msg = validate_cron(cron_expr)
    if not valid:
        out_chan.write_system_error(f"无效的 cron 表达式: {msg}")
        return

    try:
        task = get_cron_manager().create_task(
            prompt=prompt,
            cron_expression=cron_expr,
            enabled=True,
        )
        out_chan.write_menu_content(
            f"[success]任务已创建[/success]\n"
            f"ID: {task.task_id}\n"
            f"执行计划: {task.cron_expression}\n"
            f"提示词: {task.prompt}\n"
        )
    except Exception as e:
        out_chan.write_system_error(f"创建任务失败: {e}")


def _cron_delete(out_chan: BaseOutChannel, task_id: str | None):
    if not task_id:
        out_chan.write_menu_content("[warning]用法: /cron delete <任务ID>[/warning]\n")
        return
    if get_cron_manager().delete_task(task_id):
        out_chan.write_menu_content(f"[success]任务已删除: {task_id}[/success]\n")
    else:
        out_chan.write_system_error(f"删除失败，任务不存在: {task_id}")


def _cron_enable(out_chan: BaseOutChannel, task_id: str | None):
    if not task_id:
        out_chan.write_menu_content("[warning]用法: /cron enable <任务ID>[/warning]\n")
        return
    if get_cron_manager().enable_task(task_id):
        out_chan.write_menu_content(f"[success]任务已启用: {task_id}[/success]\n")
    else:
        out_chan.write_system_error(f"启用失败，任务不存在: {task_id}")


def _cron_disable(out_chan: BaseOutChannel, task_id: str | None):
    if not task_id:
        out_chan.write_menu_content("[warning]用法: /cron disable <任务ID>[/warning]\n")
        return
    if get_cron_manager().disable_task(task_id):
        out_chan.write_menu_content(f"[success]任务已禁用: {task_id}[/success]\n")
    else:
        out_chan.write_system_error(f"禁用失败，任务不存在: {task_id}")


def _cron_show(out_chan: BaseOutChannel, task_id: str | None):
    if not task_id:
        out_chan.write_menu_content("[warning]用法: /cron show <任务ID>[/warning]\n")
        return
    task = get_cron_manager().get_task(task_id)
    if not task:
        out_chan.write_system_error(f"任务不存在: {task_id}")
        return

    out_chan.write_menu_content(Panel(
        f"[bold]ID:[/] {task.task_id}\n"
        f"[bold]状态:[/] {'启用' if task.enabled else '禁用'}\n"
        f"[bold]执行计划:[/] {task.cron_expression}\n"
        f"[bold]创建时间:[/] {task.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"[bold]最后更新:[/] {task.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"[bold]最后执行:[/] {task.last_run_at.strftime('%Y-%m-%d %H:%M') if task.last_run_at else '-'}\n"
        f"\n[bold]提示词:[/]\n{task.prompt}",
        title=f"Cron 任务: {task_id}",
        border_style="cyan",
    ))


def _cron_help(out_chan: BaseOutChannel):
    table = Table(title="Cron 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/cron", "列出所有任务")
    table.add_row("/cron list", "列出所有任务")
    table.add_row("/cron create <表达式> <提示词>", "创建任务（表达式支持 5 字段或 @daily/@hourly 等）")
    table.add_row("/cron delete <id>", "删除任务")
    table.add_row("/cron enable <id>", "启用任务")
    table.add_row("/cron disable <id>", "禁用任务")
    table.add_row("/cron show <id>", "查看任务详情")
    table.add_row("/cron help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_cron(out_chan: BaseOutChannel, command: str) -> bool:
    """处理 /cron 命令，返回是否继续对话"""
    parts = command.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "list"

    if subcmd in ("list", "ls", "l"):
        _cron_list(out_chan)
    elif subcmd in ("create", "add", "new", "c"):
        _cron_create(out_chan, command)
    elif subcmd in ("delete", "remove", "del", "rm", "d"):
        _cron_delete(out_chan, parts[2] if len(parts) > 2 else None)
    elif subcmd in ("enable", "en"):
        _cron_enable(out_chan, parts[2] if len(parts) > 2 else None)
    elif subcmd in ("disable", "dis"):
        _cron_disable(out_chan, parts[2] if len(parts) > 2 else None)
    elif subcmd in ("show", "view", "s"):
        _cron_show(out_chan, parts[2] if len(parts) > 2 else None)
    elif subcmd in ("help", "h", "?"):
        _cron_help(out_chan)
    else:
        _cron_help(out_chan)

    return True


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

    # ============ Cron 定时任务命令 ============
    if cmd == "/cron" or cmd.startswith("/cron "):
        return _handle_cron(out_chan, command)

    out_chan.write_menu_content(f"[warning]未知命令: {command}[/warning]\n输入 [bold]/help[/] 查看可用命令\n")
    return True
