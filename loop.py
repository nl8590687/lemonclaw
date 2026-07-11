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
from langchain_core.messages import AIMessage
from rich.text import Text

from agent.agent import AgentService
from channels.bus import get_bus, EventMessage, EventType
from channels.ins import TerminalInput, WebhookInput, FeishuInput, CrontabInput
from channels.out import BaseOutChannel, TerminalOutputChannel, FeishuOutputChannel
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


def handle_response(out_chan: BaseOutChannel, event_msg: EventMessage, response_text: dict[str, object]):
    msg_list = response_text.get("messages", [])
    rsp_msg = msg_list[-1] if msg_list and isinstance(msg_list[-1], AIMessage) else None
    rsp_content = rsp_msg.content if rsp_msg else ""
    if not rsp_content:
        return

    if event_msg.event_type.value == EventType.LARK_MESSAGE.value:
        out_chan.write_message(rsp_content, event_msg.context)


def get_output_channel(event_msg: EventMessage) -> BaseOutChannel:
    config = get_global_config()
    event_type = event_msg.event_type
    if event_type.value == EventType.TERMINAL.value:
        return TerminalOutputChannel()
    if config.ENABLE_WEBHOOK and event_type.value == EventType.WEBHOOK.value:
        return TerminalOutputChannel()
    if event_type.value == EventType.SCHEDULED_TASK.value:
        return TerminalOutputChannel()
    if config.ENABLE_FEISHU and event_type.value == EventType.LARK_MESSAGE.value:
        return FeishuOutputChannel()
    return TerminalOutputChannel()


def loop_forever():
    svr = AgentService()
    msg_bus = get_bus()
    while True:
        try:
            event_msg: EventMessage = msg_bus.poll()
            if not event_msg:
                continue
            event_msg_content = str(event_msg.content) if len(str(event_msg.content)) < 100 else str(event_msg.content)[:100]
            svr.default_out_chan.print(Text(f"\n\n[系统] 收到事件: {event_msg.event_type.value} {event_msg_content}\n\n", style="dim"))
            msg_text: str = event_msg.content.get("text", "")
            if not event_msg:
                continue

            out_chan = get_output_channel(event_msg)
            if msg_text.strip().startswith("/"):
                if not handle_command(out_chan, agent_service=svr, command=msg_text) and isinstance(out_chan, TerminalOutputChannel):
                    break
            else:
                context = event_msg.context
                res = svr.run(msg_text.strip(), context)
                handle_response(out_chan, event_msg, res)
            svr.trim_msg_history()
        except KeyboardInterrupt:
            break
        except Exception as ex:
            svr.default_out_chan.write_system_error(f"error: {ex}")

    stop_event_source()
    # 退出前快速归档当前会话（fast=True：跳过 LLM，仅统计版抽取，不重载索引，毫秒级）
    if svr.memory:
        try:
            svr.memory.on_session_end(svr._current_messages(), fast=True)
        except Exception:
            pass
    svr.default_out_chan.print("\n\n[warning]再见！[/warning]\n")
