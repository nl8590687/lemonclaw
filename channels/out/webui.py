"""Public model tokens and results for the single owner's browser clients."""

from channels.out.base import BaseOutChannel
from channels.webui.state import emit


class WebUIOutputChannel(BaseOutChannel):
    def write_message(self, msg, context):
        emit("message", dict(content=msg, source=context.get("source", context.get("_event_type", "system"))))

    def print(self, msg):
        if isinstance(msg, str):
            emit("delta", dict(content=msg))

    def write_tool_calling(self, tool_name, param_str):
        emit("tool", dict(name=tool_name, status="running"))

    def write_tool_result(self, output):
        emit("tool", dict(status="completed", content=str(output)[:20000]))

    def write_tool_error(self, error):
        emit("error", dict(content=str(error)))

    def write_menu_content(self, content):
        emit("message", dict(content=str(content), source="command"))

    def write_system_error(self, content):
        emit("error", dict(content=str(content)))
