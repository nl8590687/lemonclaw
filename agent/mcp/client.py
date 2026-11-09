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

"""Official LangChain/FastMCP client behind the synchronous business facade.

A connection owns one event loop and one long-lived adapter context. All MCP
operations stay on that loop; browser/SSH sessions survive between tool calls.
The owner task also closes the context (AnyIO task groups require this).
"""
import asyncio
import atexit
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import logging
from threading import Thread, current_thread
from typing import Any

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


@dataclass
class ToolInfo:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return text[:half] + "\n… [MCP 结果已截断] …\n" + text[-half:]


class MCPConnection:
    """Own an official client, persistent session, and synchronous bridge."""

    def __init__(self, server_id, url, headers, connect_timeout, call_timeout,
                 result_max_chars, *, options=None, target=None):
        self.server_id, self.url, self.headers = server_id, url, headers or {}
        self.connect_timeout, self.call_timeout = connect_timeout, call_timeout
        self.result_max_chars = result_max_chars
        self.options = options or {}
        self._target = target  # in-process official server/client, for integration tests
        self.tools = []
        self.native_tools = {}
        self.protocol_version, self.server_info, self.capabilities = "", {}, {}
        self.status, self.last_error = "disconnected", None
        self._loop = self._thread = self._stop = self.adapter = self._owner = None
        self._ready = Future()

    def _transport(self):
        from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport
        if self._target is not None:
            return self._target
        kind = self.options.get("transport", "stdio" if self.options.get("command") else "http")
        if kind == "stdio":
            return StdioTransport(command=self.options["command"], args=self.options.get("args", []),
                                  env=self.options.get("env"), cwd=self.options.get("cwd"))
        if kind not in {"http", "streamable_http", "streamable-http", "sse"}:
            raise ValueError(f"不支持的 MCP transport: {kind}")
        if kind == "sse":
            return SSETransport(self.url, headers=self.headers, auth=self.options.get("auth"))
        return StreamableHttpTransport(self.url, headers=self.headers, auth=self.options.get("auth"),
                                       max_sse_event_size=32 * 1024 * 1024)

    async def _serve(self):
        self._stop = asyncio.Event()
        try:
            from fastmcp import Client
            from langchain.mcp import MCPAdapter
            target = self._transport()
            if not isinstance(target, Client):
                target = Client(target, name="lemonclaw", timeout=self.call_timeout,
                                init_timeout=self.connect_timeout, roots=self.options.get("roots"))
            self.adapter = MCPAdapter(target)
            async with self.adapter:
                client = self.adapter.client
                self.protocol_version = str(client.protocol_version or "")
                self.server_info = client.server_info.model_dump(exclude_none=True) if client.server_info else {}
                caps = client.server_capabilities
                self.capabilities = caps.model_dump(exclude_none=True) if caps else {}
                await self._refresh_tools()
                self.status = "connected"
                self._ready.set_result(None)
                await self._stop.wait()
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            elif not isinstance(exc, asyncio.CancelledError):
                self.status, self.last_error = "error", self._error(exc)
                logger.warning("MCP %s connection stopped: %s", self.server_id, self.last_error)
        finally:
            self.adapter = None

    def _worker(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._owner = self._loop.create_task(self._serve())
            self._loop.run_until_complete(self._owner)
        finally:
            tasks = asyncio.all_tasks(self._loop)
            for task in tasks:
                task.cancel()
            if tasks:
                self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def connect(self):
        if self._thread and self._thread.is_alive():
            self.disconnect()
        self.status, self.last_error = "connecting", None
        self._ready = Future()
        self._thread = Thread(target=self._worker, name=f"mcp-{self.server_id}", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=self.connect_timeout)
            atexit.register(self.disconnect)
            return True, ""
        except Exception as exc:
            self.last_error = self._error(exc)
            self.disconnect()
            self.status = "error"
            return False, self.last_error

    def disconnect(self):
        atexit.unregister(self.disconnect)
        thread, loop = self._thread, self._loop
        if thread and thread.is_alive() and loop and loop.is_running():
            if self._stop:
                loop.call_soon_threadsafe(self._stop.set)
            thread.join(timeout=self.connect_timeout)
            if thread.is_alive() and loop.is_running() and self._owner is not None:
                loop.call_soon_threadsafe(self._owner.cancel)
                thread.join(timeout=5)
        # The worker may already have closed its loop while the thread is still
        # finishing teardown. Wait for it before reporting disconnect/failure.
        if thread and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=5)
        self.status = "disconnected"
        self.native_tools = {}

    def _submit(self, coroutine, timeout=None):
        if not self._loop or not self._loop.is_running() or not self.adapter:
            coroutine.close()
            raise RuntimeError(f"MCP 服务 {self.server_id} 未连接")
        # run_coroutine_threadsafe carries the caller's contextvars, including
        # LangGraph's interrupt/resume context and per-turn provenance.
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=timeout or self.call_timeout)
        except FutureTimeout:
            future.cancel()  # propagate cancellation to the official client/server
            raise TimeoutError(f"MCP 调用超过 {timeout or self.call_timeout} 秒；远端操作是否完成需核实") from None

    async def _refresh_tools(self):
        native = await self.adapter.list_tools(cache_mode="refresh")
        self.native_tools = {tool.name: tool for tool in native}
        self.tools = [ToolInfo(tool.name, tool.description, tool.args_schema) for tool in native]

    def list_tools(self):
        return self.tools

    async def _call(self, tool_name, arguments):
        """Use SDK results directly, including content the LC converter lacks.

        The SDK owns negotiation, transports, pagination and typed requests.
        Modern human input is surfaced to the existing durable question flow;
        no sampling/model invocation is silently authorized by a remote server.
        """
        from mcp.types import InputRequiredResult, ElicitRequest, ElicitRequestFormParams, ElicitResult
        from mcp.types.version import LATEST_MODERN_VERSION, is_version_at_least
        from langgraph.types import interrupt
        client = self.adapter.client
        if not is_version_at_least(client.protocol_version, LATEST_MODERN_VERSION):
            return await client.call_tool(tool_name, arguments, raise_on_error=False)
        result = await client.session.call_tool(tool_name, arguments, allow_input_required=True)
        for _ in range(10):
            if not isinstance(result, InputRequiredResult):
                return result
            requests = result.input_requests or {}
            if any(not isinstance(request, ElicitRequest) for request in requests.values()):
                raise NotImplementedError('MCP 服务请求 sampling/roots 输入；尚未配置相应处理策略，未自动授权')
            responses = {}
            if requests:
                described = []
                for key, request in requests.items():
                    params = request.params
                    if isinstance(params, ElicitRequestFormParams):
                        described.append({'key': key, 'mode': 'form', 'message': params.message,
                                          'requested_schema': params.requested_schema})
                    else:
                        described.append({'key': key, 'mode': 'url', 'message': params.message, 'url': str(params.url)})
                answer = interrupt({'type': 'mcp_elicitation', 'tool_name': tool_name, 'requests': described})
                for key in requests:
                    value = answer['responses'][key]
                    responses[key] = ElicitResult(**value)
            result = await client.session.call_tool(tool_name, arguments, input_responses=responses,
                request_state=result.request_state, allow_input_required=True)
        raise RuntimeError('MCP 工具超过 10 轮输入/继续执行限制；未自动重试')

    @staticmethod
    def _message(result, tool_name, tool_call_id):
        from langchain_core.messages.content import create_text_block, create_image_block, create_audio_block, create_file_block
        from mcp.types import TextContent, ImageContent, AudioContent, EmbeddedResource, ResourceLink
        blocks = []
        for block in result.content:
            if isinstance(block, TextContent):
                blocks.append(create_text_block(text=block.text))
            elif isinstance(block, ImageContent):
                blocks.append(create_image_block(base64=block.data, mime_type=block.mime_type))
            elif isinstance(block, AudioContent):
                blocks.append(create_audio_block(base64=block.data, mime_type=block.mime_type))
            elif isinstance(block, EmbeddedResource):
                resource = block.resource
                if hasattr(resource, 'text'):
                    blocks.append(create_text_block(text=resource.text))
                else:
                    factory = create_image_block if (resource.mime_type or '').startswith('image/') else create_file_block
                    blocks.append(factory(base64=resource.blob, mime_type=resource.mime_type))
            elif isinstance(block, ResourceLink):
                factory = create_image_block if (block.mime_type or '').startswith('image/') else create_file_block
                blocks.append(factory(url=str(block.uri), mime_type=block.mime_type))
            else:
                raise ValueError(f'尚不支持的 MCP 内容类型: {type(block).__name__}')
        structured = getattr(result, 'structured_content', None)
        if not blocks and structured is not None:
            import json
            blocks.append(create_text_block(text=json.dumps(structured, ensure_ascii=False)))
        artifact = {'structured_content': structured} if structured is not None else None
        return ToolMessage(content=blocks or [create_text_block(text='[MCP 返回空内容]')],
            name=tool_name, tool_call_id=tool_call_id, artifact=artifact,
            status='error' if result.is_error else 'success')

    def invoke_tool(self, tool_name, arguments, tool_call_id="mcp-call", config=None):
        async def invoke():
            if tool_name not in self.native_tools:
                raise ValueError(f"MCP 工具不存在: {tool_name}")
            result = await self._call(tool_name, arguments or {})
            return self._message(result, tool_name, tool_call_id)
        return self._submit(invoke())

    def call_tool(self, tool_name, arguments):
        """CLI compatibility: render content without ever printing binary payloads."""
        try:
            message = self.invoke_tool(tool_name, arguments)
            text = truncate_text(self.render(message.content), self.result_max_chars)
            return ("❌ " if message.status == "error" else "") + text
        except Exception as exc:
            from langgraph.errors import GraphInterrupt
            if isinstance(exc, GraphInterrupt):
                raise
            return f"❌ MCP 工具调用失败: {self._error(exc)}"

    def protocol(self, operation, arguments=None):
        """Advanced operations go through the same official, persistent client."""
        async def invoke():
            client = self.adapter.client
            methods = {"list_resources", "list_resource_templates", "read_resource", "list_prompts",
                       "get_prompt", "complete", "ping"}
            if operation not in methods:
                raise ValueError(f"不支持的 MCP 操作: {operation}")
            args = dict(arguments or {})
            if operation == "complete":
                from mcp.types import PromptReference, ResourceTemplateReference
                ref = args.get("ref", {})
                args["ref"] = (PromptReference if ref.get("type") == "ref/prompt" else ResourceTemplateReference)(**ref)
            return await getattr(client, operation)(**args)
        return self._submit(invoke())

    def _error(self, exc):
        # Connection libraries may include a URL/header in exceptions. Do not
        # expose configured credentials through CLI, tools, logs, or the DB.
        text = str(exc) or type(exc).__name__
        for secret in [*self.headers.values(), *(self.options.get("env") or {}).values(), self.options.get("auth")]:
            if isinstance(secret, str) and secret:
                text = text.replace(secret, "[redacted]")
        return truncate_text(text, 2000)

    @staticmethod
    def render(content):
        if isinstance(content, str):
            return content
        return "\n".join(block.get("text", "") if block.get("type") == "text"
                         else f"[{block.get('type', 'content')}: {block.get('mime_type', '')}]"
                         for block in content if isinstance(block, dict))
