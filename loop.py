#!/usr/bin/env python
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
Loop forever
"""
from rich.text import Text

from agent.agent import AgentService
from channels.bus import get_bus, EventMessage, EventType
from channels.ins import TerminalInput, WebhookInput, FeishuInput, CrontabInput
from channels.out import BaseOutChannel, build_output_channel
from command import handle_command
from config import get_global_config


_event_sources = []


def start_event_source():
    config = get_global_config()
    terminal = TerminalInput()
    terminal.start()
    _event_sources.append(terminal)

    if config.ENABLE_WEBHOOK:
        webhook = WebhookInput()
        webhook.start()
        _event_sources.append(webhook)

    crontab = CrontabInput()
    crontab.start()
    _event_sources.append(crontab)

    if config.ENABLE_FEISHU:
        feishu = FeishuInput()
        feishu.start()
        _event_sources.append(feishu)


def stop_event_source():
    for event_source in _event_sources:
        event_source.stop()


def get_output_channel(event_msg: EventMessage | None = None) -> BaseOutChannel:
    """返回聚合输出通道：终端始终输出，飞书启用时同时输出。"""
    context = event_msg.context if event_msg is not None else None
    return build_output_channel(context)


def format_attachment_log(attachments: list[dict[str, object]]) -> str:
    """把本轮附件格式化为一行日志，便于确认文件路径已进入上下文。"""
    parts: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or "文件"
        path = item.get("path")
        parts.append(f"{kind} {path}" if path else f"{kind} 下载失败")
    return "; ".join(parts)


def loop_forever():
    svr = AgentService()
    msg_bus = get_bus()
    while True:
        out_chan = svr.default_out_chan
        try:
            event_msg: EventMessage = msg_bus.poll()
            if not event_msg:
                continue
            event_msg_content = str(event_msg.content) if len(str(event_msg.content)) < 100 else str(event_msg.content)[:100]
            svr.default_out_chan.print(Text(f"\n\n[系统] 收到事件: {event_msg.event_type.value} {event_msg_content}\n\n", style="dim"))
            msg_text: str = event_msg.content.get("text", "")
            attachments = (
                event_msg.context.get("attachments")
                if isinstance(event_msg.context, dict) else None
            )
            if not isinstance(attachments, list):
                attachments = []
            if attachments:
                svr.default_out_chan.print(
                    Text(f"[系统] 附件: {format_attachment_log(attachments)}\n", style="dim")
                )
            if not event_msg:
                continue
            if not msg_text.strip() and not attachments:
                continue

            out_chan = get_output_channel(event_msg)
            is_terminal_event = event_msg.event_type.value == EventType.TERMINAL.value
            from agent.media.commands import is_media_command, media_command
            if is_media_command(msg_text):
                question, selected, receipt = media_command(msg_text, event_msg.context)
                if receipt is not None:
                    out_chan.write_message(receipt, event_msg.context)
                    continue
                svr.run(question, event_msg.context, out_chan, attachments=selected)
                svr.trim_msg_history()
                continue
            if msg_text.strip().startswith("/"):
                if not handle_command(out_chan, agent_service=svr, command=msg_text) and is_terminal_event:
                    break
            else:
                context = event_msg.context
                svr.run(msg_text.strip(), context, out_chan, attachments=attachments)
            svr.trim_msg_history()
        except KeyboardInterrupt:
            break
        except Exception as ex:
            out_chan.write_system_error(f"error: {ex}")

    stop_event_source()
    # 退出前快速归档当前会话（fast=True：跳过 LLM，仅统计版抽取，不重载索引，毫秒级）
    if svr.memory:
        try:
            svr.memory.on_session_end(svr._current_messages(), fast=True)
        except Exception:
            pass
    svr.close()
    svr.default_out_chan.print("\n\n[warning]再见！[/warning]\n")
