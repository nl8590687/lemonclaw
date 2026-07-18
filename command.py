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

import json
import os

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
    table.add_row("/memory", "列出全部核心记忆")
    table.add_row("/memory set <key> <value>", "记住一条（fact 类型）")
    table.add_row("/memory set <type>:<key> <value>", "记住一条，指定类型")
    table.add_row("/memory get <type>:<key>", "查看单条")
    table.add_row("/memory delete <type>:<key>", "删除单条")
    table.add_row("")
    table.add_row("[bold cyan]历史会话[/]", "")
    table.add_row("/session", "列出最近会话")
    table.add_row("/session show <id>", "查看某会话的历史消息")
    table.add_row("/resume [id]", "原地续写指定 id 或最近一次会话")
    table.add_row("")
    table.add_row("[bold cyan]长期记忆块[/]", "")
    table.add_row("/chunk", "列出所有长期记忆块")
    table.add_row("/chunk add <type> <title> <content>", "添加记忆块")
    table.add_row("/chunk get <id>", "查看单条记忆块")
    table.add_row("/chunk delete <id>", "删除记忆块")
    table.add_row("/chunk search <query>", "搜索相关记忆块")
    table.add_row("")
    table.add_row("[bold cyan]Skill 管理[/]", "")
    table.add_row("/skills", "列出所有技能（/skills help 查看子命令）")
    table.add_row("/skills show <名称>", "查看技能详情")
    table.add_row("/skills enable/disable <名称>", "启用/禁用技能")
    table.add_row("/skills unload <名称>", "卸载已激活技能")
    table.add_row("/skills setup <名称>", "安装技能依赖")
    table.add_row("/skills reload", "热加载（重扫目录刷新索引）")
    table.add_row("")
    table.add_row("[bold cyan]MCP 接入[/]", "")
    table.add_row("/mcp", "列出 MCP 服务端（/mcp help 查看子命令）")
    table.add_row("/mcp add <id> <url> [headers]", "注册并连接 MCP 服务端（回写 mcp.json）")
    table.add_row("/mcp tools <id>", "查看服务端暴露的工具")
    table.add_row("/mcp reload", "重载 mcp.json（对话不中断）")
    table.add_row("")
    table.add_row("[bold cyan]多 Agent 工作流[/]", "")
    table.add_row("/wf", "列出工作流定义（/wf help 查看子命令）")
    table.add_row("/wf runs", "列出运行中/阻塞中的 run")
    table.add_row("/wf resume <id> <答复>", "续跑暂停的 run")
    table.add_row("/wf delete <id>", "删除工作流定义（含 run 与 checkpoint）")
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


def _parse_type_key(s: str) -> tuple[str, str]:
    """解析 'type:key' 或 'key'，返回 (memory_type, key)；无 ':' 时 type='fact'"""
    s = s.strip()
    if ":" in s:
        t, k = s.split(":", 1)
        return t.strip(), k.strip()
    return "fact", s


def _memory_list(out_chan: BaseOutChannel, agent_service: AgentService):
    """列出全部核心记忆"""
    memories = agent_service.list_core_memory()
    if not memories:
        out_chan.write_menu_content("[dim]当前没有核心记忆[/dim]\n")
        return
    table = Table(title="核心记忆", show_header=True, header_style="bold cyan")
    table.add_column("类型", style="bold yellow")
    table.add_column("键")
    table.add_column("值")
    table.add_column("描述", style="dim")
    for m in memories:
        table.add_row(m.memory_type, m.key, m.value, m.description or "")
    out_chan.write_menu_content(table)


def _memory_set(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """写入/更新核心记忆: /memory set [type:]<key> <value>"""
    if not rest:
        out_chan.write_menu_content(
            "[warning]用法: /memory set [type:]<key> <value>[/warning]\n"
            "示例: /memory set lang 中文\n"
            "      /memory set preference:lang 中文\n"
        )
        return
    parts = rest.split(None, 1)
    key_part = parts[0]
    value = parts[1].strip() if len(parts) > 1 else ""
    if not value:
        out_chan.write_menu_content("[warning]value 不能为空[/warning]\n")
        return
    memory_type, key = _parse_type_key(key_part)
    if not key:
        out_chan.write_menu_content("[warning]key 不能为空[/warning]\n")
        return
    if agent_service.remember(key, value, memory_type=memory_type):
        out_chan.write_menu_content(
            f"[success]✅ 已记住[/success] [{memory_type}] {key} = {value}\n"
        )
    else:
        out_chan.write_system_error("写入核心记忆失败")


def _memory_get(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """查看单条核心记忆: /memory get <type>:<key>"""
    if not rest or ":" not in rest:
        out_chan.write_menu_content("[warning]用法: /memory get <type>:<key>[/warning]\n")
        return
    memory_type, key = _parse_type_key(rest)
    mem = agent_service.get_core_memory(memory_type, key)
    if mem is None:
        out_chan.write_menu_content(f"[dim]未找到核心记忆[/dim] [{memory_type}] {key}\n")
        return
    out_chan.write_menu_content(Panel(
        f"[bold]类型:[/] {mem.memory_type}\n"
        f"[bold]键:[/] {mem.key}\n"
        f"[bold]值:[/] {mem.value}\n"
        f"[bold]描述:[/] {mem.description or '-'}\n"
        f"[bold]用户编辑:[/] {'是' if mem.is_user_edited else '否'}\n"
        f"[bold]创建:[/] {mem.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"[bold]更新:[/] {mem.updated_at.strftime('%Y-%m-%d %H:%M')}",
        title=f"核心记忆: {memory_type}:{key}",
        border_style="cyan",
    ))


def _memory_delete(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """删除核心记忆: /memory delete <type>:<key>"""
    if not rest or ":" not in rest:
        out_chan.write_menu_content("[warning]用法: /memory delete <type>:<key>[/warning]\n")
        return
    memory_type, key = _parse_type_key(rest)
    if agent_service.forget(memory_type, key):
        out_chan.write_menu_content(
            f"[success]✅ 已删除[/success] [{memory_type}] {key}\n"
        )
    else:
        out_chan.write_system_error(f"删除失败，可能不存在: [{memory_type}] {key}")


def _memory_help(out_chan: BaseOutChannel):
    table = Table(title="/memory 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/memory, /memory list", "列出全部核心记忆")
    table.add_row("/memory set <key> <value>", "记住一条（fact 类型）")
    table.add_row("/memory set <type>:<key> <value>", "记住一条，指定类型")
    table.add_row("/memory get <type>:<key>", "查看单条")
    table.add_row("/memory delete <type>:<key>", "删除单条")
    table.add_row("/memory help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_memory(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    """处理 /memory 命令（核心记忆：set/get/delete/list/help）"""
    parts = command.strip().split(None, 2)
    subcmd = parts[1].lower() if len(parts) > 1 else "list"
    rest = parts[2].strip() if len(parts) > 2 else ""

    if agent_service.memory is None:
        out_chan.write_menu_content("[warning]记忆功能未启用（ENABLE_MEMORY=false）[/warning]\n")
        return

    if subcmd in ("list", "ls", "l"):
        _memory_list(out_chan, agent_service)
    elif subcmd in ("set", "add", "remember"):
        _memory_set(out_chan, agent_service, rest)
    elif subcmd in ("get", "show"):
        _memory_get(out_chan, agent_service, rest)
    elif subcmd in ("delete", "del", "rm", "forget"):
        _memory_delete(out_chan, agent_service, rest)
    elif subcmd in ("help", "h", "?"):
        _memory_help(out_chan)
    else:
        _memory_help(out_chan)


def _session_list(out_chan: BaseOutChannel, agent_service: AgentService):
    """列出最近会话"""
    sessions = agent_service.list_sessions()
    if not sessions:
        out_chan.write_menu_content("[dim]没有任何会话记录[/dim]\n")
        return
    table = Table(title="历史会话", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("开始时间")
    table.add_column("结束时间", style="dim")
    table.add_column("归档")
    table.add_column("摘要预览")
    for s in sessions:
        start = s.start_time.strftime("%Y-%m-%d %H:%M") if s.start_time else "-"
        end = s.end_time.strftime("%Y-%m-%d %H:%M") if s.end_time else "-"
        archived = "是" if s.is_archived else "否"
        if s.summary and len(s.summary) > 30:
            summary = s.summary[:30] + "..."
        else:
            summary = s.summary or "-"
        table.add_row(str(s.id), start, end, archived, summary)
    out_chan.write_menu_content(table)


def _session_show(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """查看某会话历史消息: /session show <id>"""
    if not rest:
        out_chan.write_menu_content("[warning]用法: /session show <id>[/warning]\n")
        return
    try:
        sid = int(rest.split()[0])
    except ValueError:
        out_chan.write_menu_content("[warning]id 必须是整数[/warning]\n")
        return
    msgs = agent_service.load_session_messages(sid)
    if msgs is None:
        out_chan.write_menu_content(f"[dim]会话不存在[/dim] #{sid}\n")
        return
    if not msgs:
        out_chan.write_menu_content(f"[dim]会话 #{sid} 没有消息[/dim]\n")
        return
    role_label = {"human": "用户", "ai": "AI", "tool": "工具", "system": "系统"}
    lines = [f"= 会话 #{sid} 历史（{len(msgs)} 条）="]
    for m in msgs:
        ts = m.timestamp.strftime("%H:%M:%S") if m.timestamp else ""
        content = f"[{m.tool_name}] {m.content}" if m.tool_name else m.content
        lines.append(f"[{ts}] {role_label.get(m.role, m.role)}: {content}")
    out_chan.write_menu_content("\n".join(lines) + "\n")


def _session_help(out_chan: BaseOutChannel):
    table = Table(title="/session 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/session, /session list", "列出最近会话")
    table.add_row("/session show <id>", "查看某会话的历史消息")
    table.add_row("/session help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_session(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    """处理 /session 命令（list/show/help）"""
    parts = command.strip().split(None, 2)
    subcmd = parts[1].lower() if len(parts) > 1 else "list"
    rest = parts[2].strip() if len(parts) > 2 else ""

    if agent_service.memory is None:
        out_chan.write_menu_content("[warning]记忆功能未启用（ENABLE_MEMORY=false）[/warning]\n")
        return

    if subcmd in ("list", "ls", "l"):
        _session_list(out_chan, agent_service)
    elif subcmd in ("show", "get", "view"):
        _session_show(out_chan, agent_service, rest)
    elif subcmd in ("help", "h", "?"):
        _session_help(out_chan)
    else:
        _session_help(out_chan)


def _handle_resume(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    """处理 /resume 命令：原地续写指定 id 或最近一次会话"""
    if agent_service.memory is None:
        out_chan.write_menu_content("[warning]记忆功能未启用（ENABLE_MEMORY=false）[/warning]\n")
        return
    parts = command.strip().split(None, 1)
    sid: int | None = None
    if len(parts) > 1 and parts[1].strip():
        try:
            sid = int(parts[1].strip())
        except ValueError:
            out_chan.write_menu_content(
                "[warning]用法: /resume [id]（id 为整数，省略则恢复最近一次）[/warning]\n"
            )
            return
    # 无 id 时先确认存在可恢复会话
    if sid is None and agent_service.memory.recent_session_id() is None:
        out_chan.write_menu_content("[dim]没有可恢复的已结束会话[/dim]\n")
        return
    if agent_service.resume_session(sid):
        out_chan.write_menu_content(
            f"[success]✅ 已续写会话[/success] #{agent_service.memory.current_session_id}\n"
        )
    else:
        target = sid if sid is not None else "最近一次"
        out_chan.write_menu_content(f"[dim]恢复失败，可能会话不存在: {target}[/dim]\n")


def _chunk_list(out_chan: BaseOutChannel, agent_service: AgentService):
    """列出长期记忆块"""
    chunks = agent_service.list_chunks()
    if not chunks:
        out_chan.write_menu_content("[dim]当前没有长期记忆块[/dim]\n")
        return
    table = Table(title="长期记忆块", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("类型")
    table.add_column("标题")
    table.add_column("重要性")
    table.add_column("访问")
    table.add_column("内容预览", style="dim")
    for c in chunks:
        preview = c.content[:40] + ("..." if len(c.content) > 40 else "")
        table.add_row(str(c.id), c.chunk_type, c.title, str(c.importance),
                      str(c.access_count), preview)
    out_chan.write_menu_content(table)


def _chunk_add(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """添加长期记忆块: /chunk add <type> <title> <content>"""
    if not rest:
        out_chan.write_menu_content(
            "[warning]用法: /chunk add <type> <title> <content>[/warning]\n"
            "示例: /chunk add fact 数据库 使用 sqlite 单库\n"
        )
        return
    parts = rest.split(None, 2)
    if len(parts) < 3:
        out_chan.write_menu_content("[warning]type / title / content 均不能为空[/warning]\n")
        return
    chunk_type, title, content = parts[0], parts[1], parts[2].strip()
    cid = agent_service.add_chunk(chunk_type, title, content)
    if cid is not None:
        out_chan.write_menu_content(
            f"[success]✅ 已添加记忆块[/success] #{cid} [{chunk_type}] {title}\n"
        )
    else:
        out_chan.write_system_error("添加记忆块失败")


def _chunk_get(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """查看单条记忆块: /chunk get <id>"""
    if not rest:
        out_chan.write_menu_content("[warning]用法: /chunk get <id>[/warning]\n")
        return
    try:
        cid = int(rest.split()[0])
    except ValueError:
        out_chan.write_menu_content("[warning]id 必须是整数[/warning]\n")
        return
    c = agent_service.get_chunk(cid)
    if c is None:
        out_chan.write_menu_content(f"[dim]记忆块不存在[/dim] #{cid}\n")
        return
    out_chan.write_menu_content(Panel(
        f"[bold]ID:[/] {c.id}\n"
        f"[bold]类型:[/] {c.chunk_type}\n"
        f"[bold]标题:[/] {c.title}\n"
        f"[bold]重要性:[/] {c.importance}\n"
        f"[bold]关键词:[/] {', '.join(c.keywords) if c.keywords else '-'}\n"
        f"[bold]访问次数:[/] {c.access_count}\n"
        f"[bold]来源会话:[/] {c.source_session_id or '-'}\n"
        f"[bold]创建:[/] {c.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"\n[bold]内容:[/]\n{c.content}",
        title=f"记忆块: {c.title}",
        border_style="cyan",
    ))


def _chunk_delete(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """删除记忆块: /chunk delete <id>"""
    if not rest:
        out_chan.write_menu_content("[warning]用法: /chunk delete <id>[/warning]\n")
        return
    try:
        cid = int(rest.split()[0])
    except ValueError:
        out_chan.write_menu_content("[warning]id 必须是整数[/warning]\n")
        return
    if agent_service.delete_chunk(cid):
        out_chan.write_menu_content(f"[success]✅ 已删除记忆块[/success] #{cid}\n")
    else:
        out_chan.write_system_error(f"删除失败，可能不存在: #{cid}")


def _chunk_search(out_chan: BaseOutChannel, agent_service: AgentService, rest: str):
    """搜索记忆块: /chunk search <query>"""
    if not rest:
        out_chan.write_menu_content("[warning]用法: /chunk search <query>[/warning]\n")
        return
    results = agent_service.search_memory(rest)
    if not results:
        out_chan.write_menu_content(f"[dim]未找到相关记忆块[/dim]\n")
        return
    lines = [f"= 搜索「{rest}」命中 {len(results)} 条 ="]
    for c, score in results:
        lines.append(f"  #{c.id} [{c.chunk_type}] (重要性{c.importance}, 相关度{score:.2f}) {c.title}")
        preview = c.content[:80] + ("..." if len(c.content) > 80 else "")
        lines.append(f"    {preview}")
    out_chan.write_menu_content("\n".join(lines) + "\n")


def _chunk_help(out_chan: BaseOutChannel):
    table = Table(title="/chunk 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/chunk, /chunk list", "列出所有长期记忆块")
    table.add_row("/chunk add <type> <title> <content>", "添加记忆块")
    table.add_row("/chunk get <id>", "查看单条")
    table.add_row("/chunk delete <id>", "删除记忆块")
    table.add_row("/chunk search <query>", "搜索相关记忆块")
    table.add_row("/chunk help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_chunk(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    """处理 /chunk 命令（list/add/get/delete/search/help）"""
    parts = command.strip().split(None, 2)
    subcmd = parts[1].lower() if len(parts) > 1 else "list"
    rest = parts[2].strip() if len(parts) > 2 else ""

    if agent_service.memory is None:
        out_chan.write_menu_content("[warning]记忆功能未启用（ENABLE_MEMORY=false）[/warning]\n")
        return

    if subcmd in ("list", "ls", "l"):
        _chunk_list(out_chan, agent_service)
    elif subcmd in ("add", "new", "create"):
        _chunk_add(out_chan, agent_service, rest)
    elif subcmd in ("get", "show"):
        _chunk_get(out_chan, agent_service, rest)
    elif subcmd in ("delete", "del", "rm"):
        _chunk_delete(out_chan, agent_service, rest)
    elif subcmd in ("search", "find", "s"):
        _chunk_search(out_chan, agent_service, rest)
    elif subcmd in ("help", "h", "?"):
        _chunk_help(out_chan)
    else:
        _chunk_help(out_chan)


def _skills_list(out_chan: BaseOutChannel, agent_service: AgentService):
    """列出所有技能"""
    if not agent_service.is_skills_enabled():
        out_chan.write_menu_content("[dim]技能功能未启用[/dim]\n")
        return
    skills = agent_service.list_skills()
    if not skills:
        out_chan.write_menu_content("[dim]当前没有技能包（放入 .lemonclaw/skills/<name>-<version>/ 后执行 /skills reload）[/dim]\n")
        return
    from agent.skill import get_skill_manager
    active_mgr = get_skill_manager()
    table = Table(title="Skills 技能列表", show_header=True, header_style="bold cyan")
    table.add_column("名称", style="bold yellow")
    table.add_column("版本", style="dim")
    table.add_column("状态")
    table.add_column("配置")
    table.add_column("描述")
    for s in skills:
        active = " ●" if active_mgr.is_active(s.name) else ""
        status = ("启用" if s.enabled else "禁用") + active
        if s.required_envs:
            missing = [e for e in s.required_envs if not os.environ.get(e)]
            cfg = "✓" if not missing else f"⚠ 缺{len(missing)}"
        else:
            cfg = "—"
        table.add_row(s.name, s.version, status, cfg, s.description)
    out_chan.write_menu_content(table)


def _skills_show(out_chan: BaseOutChannel, agent_service: AgentService, name: str | None):
    """查看技能详情"""
    if not agent_service.is_skills_enabled():
        out_chan.write_menu_content("[dim]技能功能未启用[/dim]\n")
        return
    if not name:
        out_chan.write_menu_content("[warning]用法: /skills show <技能名>[/warning]\n")
        return
    skill = agent_service.get_skill(name)
    if not skill:
        out_chan.write_system_error(f"技能不存在: {name}")
        return
    # 所需环境变量配置状态（不显示值）
    if skill.required_envs:
        env_lines = [f"  {'✓' if os.environ.get(e) else '✗'} {e}" for e in skill.required_envs]
    else:
        env_lines = ["  （无）"]
    env_block = "\n".join(env_lines)
    # 内容预览
    from agent.skill import get_skill_manager
    content = get_skill_manager().registry.get_full_content(name) or ""
    preview = content[:500] + ("..." if len(content) > 500 else "")
    out_chan.write_menu_content(Panel(
        f"[bold]名称:[/] {skill.name}\n"
        f"[bold]版本:[/] {skill.version}\n"
        f"[bold]状态:[/] {'启用' if skill.enabled else '禁用'}\n"
        f"[bold]目录:[/] {skill.dir_path}\n"
        f"[bold]所需环境变量:[/]\n{env_block}\n"
        f"[bold]加载次数:[/] {skill.access_count}\n"
        f"\n[bold]内容预览:[/]\n{preview}",
        title=f"Skill: {name}",
        border_style="cyan",
    ))


def _skills_enable(out_chan: BaseOutChannel, agent_service: AgentService, name: str | None):
    if not name:
        out_chan.write_menu_content("[warning]用法: /skills enable <技能名>[/warning]\n")
        return
    if agent_service.enable_skill(name):
        out_chan.write_menu_content(f"[success]已启用技能: {name}[/success]\n")
    else:
        out_chan.write_system_error(f"启用失败，技能不存在: {name}")


def _skills_disable(out_chan: BaseOutChannel, agent_service: AgentService, name: str | None):
    if not name:
        out_chan.write_menu_content("[warning]用法: /skills disable <技能名>[/warning]\n")
        return
    if agent_service.disable_skill(name):
        out_chan.write_menu_content(f"[success]已禁用技能: {name}[/success]\n")
    else:
        out_chan.write_system_error(f"禁用失败，技能不存在: {name}")


def _skills_unload(out_chan: BaseOutChannel, agent_service: AgentService, name: str | None):
    if not name:
        out_chan.write_menu_content("[warning]用法: /skills unload <技能名>[/warning]\n")
        return
    out_chan.write_menu_content(f"{agent_service.unload_skill(name)}\n")


def _skills_setup(out_chan: BaseOutChannel, agent_service: AgentService, name: str | None):
    """安装技能依赖（Python venv / Node）"""
    if not name:
        out_chan.write_menu_content("[warning]用法: /skills setup <技能名>[/warning]\n")
        return
    out_chan.write_menu_content(f"正在安装 {name} 依赖...\n")
    ok, msg = agent_service.setup_skill_deps(name)
    if ok:
        out_chan.write_menu_content(f"[success]✅ {name}: {msg}[/success]\n")
    else:
        out_chan.write_system_error(f"❌ {name} 依赖安装失败: {msg}")


def _skills_reload(out_chan: BaseOutChannel, agent_service: AgentService):
    """热加载：重扫目录、刷新索引与上下文"""
    if not agent_service.is_skills_enabled():
        out_chan.write_menu_content("[dim]技能功能未启用[/dim]\n")
        return
    agent_service.reload_skills()
    count = len(agent_service.list_skills())
    out_chan.write_menu_content(f"[success]已热加载 {count} 个技能（活跃技能内容已刷新）[/success]\n")


def _skills_help(out_chan: BaseOutChannel):
    table = Table(title="Skills 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/skills", "列出所有技能")
    table.add_row("/skills list", "列出所有技能")
    table.add_row("/skills show <名称>", "查看技能详情（含所需环境变量配置状态）")
    table.add_row("/skills enable <名称>", "启用技能")
    table.add_row("/skills disable <名称>", "禁用技能")
    table.add_row("/skills unload <名称>", "卸载已激活技能（停止注入其全文）")
    table.add_row("/skills setup <名称>", "安装技能依赖（Python venv / Node）")
    table.add_row("/skills reload", "热加载（重扫目录，刷新索引与上下文）")
    table.add_row("/skills help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_skills(out_chan: BaseOutChannel, agent_service: AgentService, command: str) -> bool:
    """处理 /skills 命令，返回是否继续对话"""
    parts = command.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "list"
    name = parts[2] if len(parts) > 2 else None

    if subcmd in ("list", "ls", "l"):
        _skills_list(out_chan, agent_service)
    elif subcmd in ("show", "get", "view"):
        _skills_show(out_chan, agent_service, name)
    elif subcmd in ("enable", "en"):
        _skills_enable(out_chan, agent_service, name)
    elif subcmd in ("disable", "dis"):
        _skills_disable(out_chan, agent_service, name)
    elif subcmd in ("unload", "ul"):
        _skills_unload(out_chan, agent_service, name)
    elif subcmd in ("setup", "install"):
        _skills_setup(out_chan, agent_service, name)
    elif subcmd in ("reload", "rl"):
        _skills_reload(out_chan, agent_service)
    elif subcmd in ("help", "h", "?"):
        _skills_help(out_chan)
    else:
        _skills_help(out_chan)

    return True


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


# ============ MCP 接入命令 ============

_MCP_STATUS_LABEL = {
    "connected": "[green]已连接[/]",
    "connecting": "[yellow]连接中[/]",
    "error": "[red]错误[/]",
    "disconnected": "[dim]未连接[/]",
}


def _mcp_list(out_chan: BaseOutChannel, agent_service: AgentService):
    servers = agent_service.list_mcp_servers()
    if not servers:
        out_chan.write_menu_content("[dim]当前没有 MCP 服务端（编辑 .lemonclaw/mcp.json 或 /mcp add 注册）[/dim]\n")
        return
    table = Table(title="MCP 服务端", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("状态")
    table.add_column("工具数")
    table.add_column("启用")
    table.add_column("调用")
    table.add_column("URL")
    for s in servers:
        status = _MCP_STATUS_LABEL.get(s.status, s.status)
        if s.status == "error" and s.last_error:
            status += f"\n[dim]{(s.last_error or '')[:60]}[/]"
        table.add_row(s.server_id, status, str(s.tool_count),
                      "✓" if s.enabled else "✗", str(s.access_count), s.url)
    out_chan.write_menu_content(table)


def _mcp_add(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    parts = command.split(None, 3)
    if len(parts) < 4:
        out_chan.write_menu_content(
            "[warning]用法: /mcp add <id> <url> [headers_json][/warning]\n"
            "示例: /mcp add mindoc https://host/mcp\n"
            '      /mcp add mindoc https://host/mcp {"Authorization":"Bearer xxx"}\n'
        )
        return
    server_id = parts[2]
    rest = parts[3].strip()
    sub = rest.split(None, 1)
    url = sub[0]
    headers: dict = {}
    if len(sub) > 1 and sub[1].strip():
        try:
            headers = json.loads(sub[1].strip())
            if not isinstance(headers, dict):
                out_chan.write_menu_content("[warning]headers 须为 JSON 对象[/warning]\n")
                return
        except json.JSONDecodeError as e:
            out_chan.write_menu_content(f"[warning]headers JSON 解析失败: {e}[/warning]\n")
            return
    ok, msg = agent_service.add_mcp_server(server_id, url, headers)
    if ok:
        out_chan.write_menu_content(f"[success]✅ {server_id}: {msg}[/success]\n")
    else:
        out_chan.write_system_error(f"❌ {server_id}: {msg}")


def _mcp_remove(out_chan: BaseOutChannel, agent_service: AgentService, parts: list):
    server_id = parts[2] if len(parts) > 2 else None
    if not server_id:
        out_chan.write_menu_content("[warning]用法: /mcp remove <id>[/warning]\n")
        return
    if agent_service.remove_mcp_server(server_id):
        out_chan.write_menu_content(f"[success]✅ 已删除 MCP 服务: {server_id}[/success]\n")
    else:
        out_chan.write_system_error(f"删除失败，MCP 服务不存在: {server_id}")


def _mcp_enable(out_chan: BaseOutChannel, agent_service: AgentService, parts: list):
    server_id = parts[2] if len(parts) > 2 else None
    if not server_id:
        out_chan.write_menu_content("[warning]用法: /mcp enable <id>[/warning]\n")
        return
    ok, msg = agent_service.enable_mcp_server(server_id)
    if ok:
        out_chan.write_menu_content(f"[success]✅ {server_id}: {msg}[/success]\n")
    else:
        out_chan.write_system_error(f"❌ {server_id}: {msg}")


def _mcp_disable(out_chan: BaseOutChannel, agent_service: AgentService, parts: list):
    server_id = parts[2] if len(parts) > 2 else None
    if not server_id:
        out_chan.write_menu_content("[warning]用法: /mcp disable <id>[/warning]\n")
        return
    ok, msg = agent_service.disable_mcp_server(server_id)
    if ok:
        out_chan.write_menu_content(f"[success]✅ {server_id}: {msg}[/success]\n")
    else:
        out_chan.write_system_error(f"❌ {server_id}: {msg}")


def _mcp_reconnect(out_chan: BaseOutChannel, agent_service: AgentService, parts: list):
    server_id = parts[2] if len(parts) > 2 else None
    if not server_id:
        out_chan.write_menu_content("[warning]用法: /mcp reconnect <id>[/warning]\n")
        return
    ok, msg = agent_service.reconnect_mcp_server(server_id)
    if ok:
        out_chan.write_menu_content(
            f"[success]✅ {server_id}: 已重连（发现 {len(agent_service.list_mcp_tools(server_id))} 个工具）[/success]\n"
        )
    else:
        out_chan.write_system_error(f"❌ {server_id}: {msg}")


def _mcp_tools(out_chan: BaseOutChannel, agent_service: AgentService, parts: list):
    server_id = parts[2] if len(parts) > 2 else None
    if not server_id:
        out_chan.write_menu_content("[warning]用法: /mcp tools <id>[/warning]\n")
        return
    tools = agent_service.list_mcp_tools(server_id)
    if not tools:
        out_chan.write_menu_content(f"[dim]MCP 服务 {server_id} 暂无工具（未连接或未发现）[/dim]\n")
        return
    table = Table(title=f"MCP 工具: {server_id}", show_header=True, header_style="bold cyan")
    table.add_column("工具名", style="bold yellow")
    table.add_column("描述")
    for t in tools:
        table.add_row(t.name, t.description)
    out_chan.write_menu_content(table)


def _mcp_reload(out_chan: BaseOutChannel, agent_service: AgentService):
    agent_service.reload_mcp()
    servers = agent_service.list_mcp_servers()
    connected = sum(1 for s in servers if s.status == "connected")
    out_chan.write_menu_content(
        f"[success]✅ 已重载 {len(servers)} 个服务端（{connected} 个已连接，对话未中断）[/success]\n"
    )


def _mcp_call(out_chan: BaseOutChannel, agent_service: AgentService, command: str):
    parts = command.split(None, 3)
    if len(parts) < 4:
        out_chan.write_menu_content(
            "[warning]用法: /mcp call <id> <tool> [json_args][/warning]\n"
            '示例: /mcp call mindoc search {"query":"x"}\n'
        )
        return
    server_id = parts[2]
    rest = parts[3].strip()
    sub = rest.split(None, 1)
    tool_name = sub[0]
    arguments: dict = {}
    if len(sub) > 1 and sub[1].strip():
        try:
            arguments = json.loads(sub[1].strip())
            if not isinstance(arguments, dict):
                out_chan.write_menu_content("[warning]args 须为 JSON 对象[/warning]\n")
                return
        except json.JSONDecodeError as e:
            out_chan.write_menu_content(f"[warning]args JSON 解析失败: {e}[/warning]\n")
            return
    result = agent_service.call_mcp_tool(server_id, tool_name, arguments)
    out_chan.write_menu_content(f"[bold]调用 {server_id}/{tool_name}：[/bold]\n{result}\n")


def _mcp_help(out_chan: BaseOutChannel):
    table = Table(title="MCP 命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/mcp", "列出所有 MCP 服务端")
    table.add_row("/mcp list", "列出所有 MCP 服务端")
    table.add_row("/mcp add <id> <url> [headers_json]", "注册并连接 MCP 服务端（回写 mcp.json）")
    table.add_row("/mcp remove <id>", "删除 MCP 服务端（从 mcp.json 移除）")
    table.add_row("/mcp enable <id>", "启用 MCP 服务端")
    table.add_row("/mcp disable <id>", "禁用 MCP 服务端（断开连接）")
    table.add_row("/mcp tools <id>", "列出该服务端暴露的工具")
    table.add_row("/mcp reconnect <id>", "重新连接服务端")
    table.add_row("/mcp reload", "重载 mcp.json 并重连所有（对话不中断）")
    table.add_row("/mcp call <id> <tool> [json_args]", "手动调用某工具（调试用）")
    table.add_row("/mcp help", "显示本帮助")
    out_chan.write_menu_content(table)


def _handle_mcp(out_chan: BaseOutChannel, agent_service: AgentService, command: str) -> bool:
    """处理 /mcp 命令，返回是否继续对话"""
    parts = command.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "list"

    if not agent_service.is_mcp_enabled():
        out_chan.write_menu_content("[dim]MCP 功能未启用（ENABLE_MCP=false）[/dim]\n")
        return True

    tool_changed = False
    if subcmd in ("list", "ls", "l"):
        _mcp_list(out_chan, agent_service)
    elif subcmd in ("add", "new"):
        _mcp_add(out_chan, agent_service, command)
        tool_changed = True
    elif subcmd in ("remove", "rm", "del"):
        _mcp_remove(out_chan, agent_service, parts)
        tool_changed = True
    elif subcmd in ("enable", "en"):
        _mcp_enable(out_chan, agent_service, parts)
        tool_changed = True
    elif subcmd in ("disable", "dis"):
        _mcp_disable(out_chan, agent_service, parts)
        tool_changed = True
    elif subcmd in ("tools", "t"):
        _mcp_tools(out_chan, agent_service, parts)
    elif subcmd in ("reconnect", "rc"):
        _mcp_reconnect(out_chan, agent_service, parts)
        tool_changed = True
    elif subcmd in ("reload", "rl"):
        _mcp_reload(out_chan, agent_service)   # reload_mcp 内部已重建 agent
    elif subcmd in ("call", "c"):
        _mcp_call(out_chan, agent_service, command)
    elif subcmd in ("help", "h", "?"):
        _mcp_help(out_chan)
    else:
        _mcp_help(out_chan)

    if tool_changed:
        agent_service.rebuild_mcp_tools()
    return True


# ============ 多 Agent 工作流命令 ============

def _handle_wf(out_chan: BaseOutChannel, agent_service: AgentService, command: str) -> bool:
    """处理 /wf 命令，返回是否继续对话"""
    parts = command.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "list"

    if not agent_service.is_workflow_enabled():
        out_chan.write_menu_content("[dim]工作流功能未启用（ENABLE_WORKFLOW=false）[/dim]\n")
        return True

    if subcmd in ("list", "ls", "l"):
        _wf_list(out_chan, agent_service)
    elif subcmd in ("show", "s"):
        _wf_show(out_chan, agent_service, parts)
    elif subcmd in ("runs", "r", "ps"):
        _wf_runs(out_chan, agent_service, parts)
    elif subcmd in ("resume", "rs"):
        _wf_resume(out_chan, agent_service, command)
    elif subcmd in ("cancel", "c"):
        _wf_cancel(out_chan, agent_service, parts)
    elif subcmd in ("delete", "del", "rm"):
        _wf_delete(out_chan, agent_service, parts)
    elif subcmd in ("help", "h", "?"):
        _wf_help(out_chan)
    else:
        _wf_help(out_chan)
    return True


def _wf_list(out_chan, agent_service):
    wfs = agent_service.list_workflows()
    if not wfs:
        out_chan.write_menu_content("（无工作流定义）\n")
        return
    lines = ["工作流定义：\n"]
    for w in wfs:
        err = f" ❌{w.last_error[:30]}" if w.last_error else ""
        lines.append(f"  {w.workflow_id} | {w.name} | v{w.version} | {'启用' if w.enabled else '禁用'}{err}\n")
    out_chan.write_menu_content("".join(lines))


def _wf_show(out_chan, agent_service, parts):
    run_id = parts[2] if len(parts) > 2 else ""
    if not run_id:
        out_chan.write_menu_content("用法: /wf show <id>\n")
        return
    wf = agent_service.get_workflow(run_id)
    out_chan.write_menu_content(f"{wf.spec if wf else '❌ Not Found'}\n")


def _wf_runs(out_chan, agent_service, parts):
    status = parts[2] if len(parts) > 2 else "active"
    runs = agent_service.list_workflow_runs(status=status, limit=20)
    if not runs:
        out_chan.write_menu_content(f"（无 {status} 状态的 run）\n")
        return
    lines = [f"工作流 run（{status}，{len(runs)}）:\n"]
    for r in runs:
        line = f"  {r.run_id} | {r.workflow_id} | {r.status}"
        if r.loop_kind:
            line += f" | {r.loop_kind}"
        line += f" | {r.updated_at}\n"
        lines.append(line)
    out_chan.write_menu_content("".join(lines))


def _wf_resume(out_chan, agent_service, command):
    parts = command.strip().split(None, 2)
    if len(parts) < 3:
        out_chan.write_menu_content("用法: /wf resume <run_id> <答复>\n")
        return
    run_id = parts[1]
    value = parts[2]
    result = agent_service.resume_workflow_run(run_id, value, {})
    if "error" in result:
        out_chan.write_menu_content(f"❌ {result['error']}\n")
    else:
        out_chan.write_menu_content(f"✅ run {run_id} 已续跑\n")


def _wf_cancel(out_chan, agent_service, parts):
    run_id = parts[2] if len(parts) > 2 else ""
    if not run_id:
        out_chan.write_menu_content("用法: /wf cancel <run_id>\n")
        return
    ok, msg = agent_service.cancel_workflow_run(run_id)
    out_chan.write_menu_content(f"{'✅' if ok else '❌'} {msg}\n")


def _wf_delete(out_chan, agent_service, parts):
    wf_id = parts[2] if len(parts) > 2 else ""
    if not wf_id:
        out_chan.write_menu_content("用法: /wf delete <workflow_id>\n")
        return
    ok, msg = agent_service.delete_workflow(wf_id)
    out_chan.write_menu_content(f"{'✅' if ok else '❌'} {msg}\n")


def _wf_help(out_chan):
    out_chan.write_menu_content(
        "/wf 命令组：\n"
        "  /wf list            列出工作流定义\n"
        "  /wf show <id>       展示指定工作流规格定义详情\n"
        "  /wf runs [status]   列出 run（active/running/paused/all）\n"
        "  /wf resume <id> <答复>  续跑暂停的 run\n"
        "  /wf cancel <id>     取消 run\n"
        "  /wf delete <id>     删除工作流定义（含全部 run 与 checkpoint）\n"
        "  /wf help            帮助\n"
    )


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

    # 核心记忆命令
    if cmd == "/memory" or cmd.startswith("/memory "):
        _handle_memory(out_chan, agent_service, command)
        return True

    # 历史会话命令
    if cmd == "/session" or cmd.startswith("/session "):
        _handle_session(out_chan, agent_service, command)
        return True

    if cmd == "/resume" or cmd.startswith("/resume "):
        _handle_resume(out_chan, agent_service, command)
        return True

    # 长期记忆块命令
    if cmd == "/chunk" or cmd.startswith("/chunk "):
        _handle_chunk(out_chan, agent_service, command)
        return True

    # ============ Skill 技能命令 ============
    if cmd == "/skills" or cmd.startswith("/skills "):
        return _handle_skills(out_chan, agent_service, command)

    # ============ MCP 接入命令 ============
    if cmd == "/mcp" or cmd.startswith("/mcp "):
        return _handle_mcp(out_chan, agent_service, command)

    # ============ 多 Agent 工作流命令 ============
    if cmd == "/wf" or cmd.startswith("/wf "):
        return _handle_wf(out_chan, agent_service, command)

    # ============ Cron 定时任务命令 ============
    if cmd == "/cron" or cmd.startswith("/cron "):
        return _handle_cron(out_chan, command)

    out_chan.write_menu_content(f"[warning]未知命令: {command}[/warning]\n输入 [bold]/help[/] 查看可用命令\n")
    return True
