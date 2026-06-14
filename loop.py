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

from agent.agent import AgentService
from channels.bus import get_bus, EventMessage, EventType
from channels.ins import TerminalInput
from channels.out import BaseOutChannel, TerminalOutputChannel
from command import handle_command


_event_sources = []


def start_event_source():
    terminal = TerminalInput()
    terminal.start()
    _event_sources.append(terminal)


def stop_event_source():
    for event_source in _event_sources:
        event_source.stop()


def handle_response(event_msg: EventMessage, response_text: str):
    pass


def get_output_channel(event_msg: EventMessage) -> BaseOutChannel:
    event_type = event_msg.event_type
    if event_type.value == EventType.TERMINAL.value:
        return TerminalOutputChannel()
    return TerminalOutputChannel()


def loop_forever():
    svr = AgentService()
    msg_bus = get_bus()
    while True:
        try:
            event_msg: EventMessage = msg_bus.poll()
            if not event_msg:
                continue
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
                handle_response(event_msg, res)
            svr.trim_msg_history()
        except KeyboardInterrupt:
            break
        except EOFError:
            pass

    stop_event_source()
    svr.default_out_chan.print("\n\n[warning]再见！[/warning]\n")
