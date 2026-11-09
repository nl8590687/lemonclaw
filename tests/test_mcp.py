"""Official MCP integration without external credentials or model API calls."""
import asyncio
import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from fastmcp import FastMCP
from fastmcp.utilities.types import Image as MCPImage
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from langgraph.errors import GraphInterrupt

from agent.mcp.client import MCPConnection
from agent.mcp.tools import MCPToolWrapper, create_protocol_tool
from agent.questions import begin_question_turn, reset_question_turn, parse_terminal
import dao.db as db


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db, '_global_db_path', None)
    return db.get_db_path()


@pytest.fixture
def connection():
    server = FastMCP('integration')
    @server.tool
    def echo(payload: dict, optional: str | None = None):
        return {'payload': payload, 'optional': optional}
    @server.tool
    def broken():
        raise ValueError('server failure')
    @server.tool
    async def slow():
        await asyncio.sleep(10)
        return 'finished'
    @server.tool
    def screenshot():
        stream = io.BytesIO()
        Image.new('RGB', (2, 2), 'red').save(stream, 'PNG')
        return MCPImage(data=stream.getvalue(), format='png')
    @server.resource('test://greeting')
    def greeting():
        return 'hello resource'
    @server.prompt
    def greet(name: str):
        return f'hello {name}'
    conn = MCPConnection('demo', '', {}, 15, 15, 20000, target=server)
    assert conn.connect() == (True, '')
    try:
        yield conn
    finally:
        conn.disconnect()
    assert not conn._thread.is_alive()


def wrapper(conn, remote):
    manager = SimpleNamespace(invoke_tool=lambda sid, name, args, cid, cfg: conn.invoke_tool(name, args, cid, cfg))
    return MCPToolWrapper(conn, manager, remote, remote, conn.native_tools[remote].args_schema, f'mcp__demo__{remote}')


def call(tool, args=None):
    return tool.invoke({'name': tool.name, 'args': args or {}, 'id': 'original-id', 'type': 'tool_call'})


def test_schema_null_and_structured_content(connection):
    tool = wrapper(connection, 'echo')
    assert tool.args_schema['properties']['optional']['anyOf']
    result = call(tool, {'payload': {'nested': {'values': [1, 'x']}}, 'optional': None})
    assert result.tool_call_id == 'original-id'
    assert result.name == tool.name
    assert result.status == 'success'
    assert result.artifact['structured_content']['optional'] is None
    assert result.artifact['structured_content']['payload']['nested']['values'] == [1, 'x']


def test_error_keeps_status(connection):
    result = call(wrapper(connection, 'broken'))
    assert result.status == 'error'
    assert 'server failure' in connection.render(result.content)
    assert connection.call_tool('broken', {}).startswith('❌')


def test_same_adapter_session_used_across_calls(connection):
    identity = connection.adapter.client
    call(wrapper(connection, 'echo'), {'payload': {}})
    call(wrapper(connection, 'echo'), {'payload': {}})
    assert connection.adapter.client is identity
    assert identity.is_connected()


def test_binary_image_survives_official_conversion(connection):
    result = call(wrapper(connection, 'screenshot'))
    block = next(b for b in result.content if b['type'] == 'image')
    assert base64.b64decode(block['base64']).startswith(b'\x89PNG')
    assert '[image:' in connection.call_tool('screenshot', {})


def test_mcp_images_checkpoint_refs_and_vision_toggle(connection, database):
    from agent.media.images import adapt_messages, REFS
    token = begin_question_turn({'source': 'terminal'}, 'look', 'session')
    try:
        result = call(wrapper(connection, 'screenshot'))
    finally:
        reset_question_turn(token)
    assert result.additional_kwargs[REFS]
    assert 'base64' not in json.dumps(result.model_dump(), ensure_ascii=False)
    messages, vision = adapt_messages([result], True)
    assert vision and messages[0].content[-1]['image_url']['url'].startswith('data:image/png;base64,')
    messages, vision = adapt_messages([result], False)
    assert not vision and 'base64,' not in str(messages[0].content)


def test_resources_and_prompts(connection):
    assert str(connection.protocol('list_resources')[0].uri) == 'test://greeting'
    assert connection.protocol('read_resource', {'uri': 'test://greeting'})[0].text == 'hello resource'
    assert connection.protocol('list_prompts')[0].name == 'greet'
    result = call(create_protocol_tool(connection, 'mcp__demo__protocol'), {'operation': 'get_prompt',
                      'arguments': {'name': 'greet', 'arguments': {'name': 'Ada'}}})
    assert 'hello Ada' in connection.render(result.content)


def test_timeout_cancels_request_without_retry(connection):
    connection.call_timeout = .05
    result = call(wrapper(connection, 'slow'))
    assert result.status == 'error' and '需核实' in result.content
    # Cancellation does not corrupt the shared client.
    assert call(wrapper(connection, 'echo'), {'payload': {}}).status == 'success'


def test_disconnected_wrapper_fails_closed(connection):
    tool = wrapper(connection, 'echo')
    connection.disconnect()
    assert call(tool, {'payload': {}}).status == 'error'


def test_redaction_and_text_limit(connection):
    connection.headers = {'Authorization': 'Bearer supersecret'}
    assert 'supersecret' not in connection._error(ValueError('failed Bearer supersecret'))
    connection.result_max_chars = 60
    result = call(wrapper(connection, 'echo'), {'payload': {'data': 'X' * 300}})
    assert '已截断' in connection.render(result.content)
    assert result.artifact['structured_content']['payload']['data'] == 'X' * 300


def test_interrupt_crosses_thread_and_resumes_durably(connection, database):
    """Use the real worker/graph boundaries, independent of MCP server era."""
    from agent.mcp.elicitation import persist_interrupt, resume_value
    from dao.question import QuestionDAO
    request = {'type': 'mcp_elicitation', 'tool_name': 'approval', 'requests': [
        {'key': 'answer', 'mode': 'form', 'message': 'Name?',
         'requested_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}}]}
    async def remote():
        return interrupt(request)
    def node(state):
        try:
            answer = connection._submit(remote())
        except GraphInterrupt as exc:
            raise persist_interrupt(exc, 'demo') from None
        return {'answer': answer}
    graph = StateGraph(dict)
    graph.add_node('tool', node)
    graph.add_edge(START, 'tool'); graph.add_edge('tool', END)
    graph = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'test'}}
    token = begin_question_turn({'source': 'terminal'}, 'go', 'session')
    try:
        result = graph.invoke({}, config)
        payload = result['__interrupt__'][0].value
        assert payload['kind'] == 'ask_user_question'
        row = QuestionDAO().get(payload['question_id'])
        with pytest.raises(ValueError, match='JSON Schema'):
            parse_terminal(row['payload'], '1:{"name":42}')
        answer = parse_terminal(row['payload'], '1:{"name":"Ada"}')
        QuestionDAO().submit(row['question_id'], answer)
        row = QuestionDAO().get(row['question_id'])
        result = graph.invoke(Command(resume=resume_value(row)), config)
        assert result['answer']['responses']['answer']['content'] == {'name': 'Ada'}
    finally:
        reset_question_turn(token)


def test_manager_compatibility_and_statistics(connection, database, monkeypatch):
    from agent.mcp.manager import MCPManager
    import agent.mcp.manager as module
    monkeypatch.setattr(module, 'get_global_config', lambda: SimpleNamespace(
        MCP_CONNECT_TIMEOUT=10, MCP_CALL_TIMEOUT=10, MCP_MAX_TOOLS=100, MCP_RESULT_MAX_CHARS=20000))
    path = database.parent / 'mcp.json'
    path.write_text(json.dumps({'demo': {'url': 'http://localhost:1234/mcp', 'headers': {}, 'auto_connect': False}}))
    manager = MCPManager()
    monkeypatch.setattr(manager, '_build_connection', lambda server: connection)
    # The test connection is already live; connect() itself is covered by fixtures.
    manager._connections['demo'] = connection
    tools = manager.get_langchain_tools()
    assert any(t.name == 'mcp__demo__echo' for t in tools)
    assert any(t.name == 'mcp__demo__protocol' for t in tools)
    call(next(t for t in tools if t.name == 'mcp__demo__echo'), {'payload': {}})
    assert manager.get_server('demo').access_count == 1
    call(next(t for t in tools if t.name == 'mcp__demo__broken'))
    assert manager.get_server('demo').access_count == 1
    assert 'payload' in manager.list_tools('demo')[0].input_schema['properties']
    assert manager.disable_server('demo')[0]
    assert not manager.get_server('demo').enabled
    assert not manager.get_langchain_tools()


def test_audio_and_embedded_resources_keep_standard_content():
    from mcp.types import AudioContent, TextContent, EmbeddedResource, TextResourceContents, ResourceLink
    raw = SimpleNamespace(content=[AudioContent(type='audio', data='AA==', mime_type='audio/wav'),
        EmbeddedResource(type='resource', resource=TextResourceContents(uri='test://text', text='embedded')),
        ResourceLink(type='resource_link', uri='https://example.com/file', name='file', mime_type='application/pdf')],
        structured_content={'key': 1}, is_error=False)
    result = MCPConnection._message(raw, 'test', 'id')
    assert [block['type'] for block in result.content] == ['audio', 'text', 'file']
    assert result.artifact['structured_content'] == {'key': 1}


def test_stdio_transport(tmp_path):
    import sys
    script = tmp_path / 'server.py'
    script.write_text('from fastmcp import FastMCP\ns=FastMCP("stdio")\n'
                      '@s.tool\ndef echo(text:str)->str:return text\ns.run()\n')
    conn = MCPConnection('local', '', {}, 30, 10, 20000,
                         options={'transport': 'stdio', 'command': sys.executable, 'args': [str(script)]})
    try:
        assert conn.connect() == (True, '')
        assert conn.call_tool('echo', {'text': 'stdio works'}) == 'stdio works'
    finally:
        conn.disconnect()


def test_real_mcp_elicitation_round_trip(database):
    from fastmcp import Context
    from pydantic import BaseModel
    from dao.question import QuestionDAO
    from agent.mcp.elicitation import resume_value
    class Name(BaseModel):
        name: str
    server = FastMCP('human')
    @server.tool
    async def approval(ctx: Context):
        from mcp.types import InputRequiredResult, ElicitRequest, ElicitRequestFormParams
        if not ctx.input_responses:
            return InputRequiredResult(input_requests={'answer': ElicitRequest(params=ElicitRequestFormParams(
                message='Your name?', requested_schema=Name.model_json_schema()))})
        response = ctx.input_responses['answer']
        return response.content['name'] if response.action == 'accept' else 'cancelled' 
    conn = MCPConnection('human', '', {}, 10, 10, 20000, target=server)
    assert conn.connect() == (True, '')
    tool = wrapper(conn, 'approval')
    def node(state):
        return {'answer': call(tool)}
    graph = StateGraph(dict)
    graph.add_node('tool', node); graph.add_edge(START, 'tool'); graph.add_edge('tool', END)
    graph = graph.compile(checkpointer=InMemorySaver())
    config = {'configurable': {'thread_id': 'human'}}
    token = begin_question_turn({'source': 'terminal'}, 'approval', 'session')
    try:
        result = graph.invoke({}, config)
        assert '__interrupt__' in result, result
        qid = result['__interrupt__'][0].value['question_id']
        row = QuestionDAO().get(qid)
        QuestionDAO().submit(qid, parse_terminal(row['payload'], '1:{"name":"Ada"}'))
        result = graph.invoke(Command(resume=resume_value(QuestionDAO().get(qid))), config)
        assert 'Ada' in conn.render(result['answer'].content)
    finally:
        reset_question_turn(token)
        conn.disconnect()


@pytest.fixture
def http_server(tmp_path):
    import socket
    import subprocess
    import sys
    import time
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    script = tmp_path / 'http_server.py'
    script.write_text('from fastmcp import FastMCP\ns=FastMCP("http")\n'
        '@s.tool\ndef echo(text:str)->str:return text\n'
        f's.run(transport="http", host="127.0.0.1", port={port}, show_banner=False)\n')
    with (tmp_path / 'server.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, str(script)], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail((tmp_path / 'server.log').read_text())
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                pytest.fail('HTTP test server did not start')
            yield f'http://127.0.0.1:{port}/mcp'
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
def test_streamable_http_protocol_eras(http_server, mode):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    target = Client(StreamableHttpTransport(http_server, headers={'X-Test': 'credential'}), mode=mode)
    conn = MCPConnection('http', http_server, {}, 15, 10, 20000, target=target)
    try:
        assert conn.connect() == (True, '')
        assert conn.call_tool('echo', {'text': 'HTTP works'}) == 'HTTP works'
        assert conn.protocol_version.startswith('2025' if mode == 'legacy' else '2026')
    finally:
        conn.disconnect()


def test_config_named_remote_argument_is_not_overwritten():
    server = FastMCP('config')
    @server.tool
    def configure(config: dict):
        return config
    conn = MCPConnection('config', '', {}, 10, 10, 20000, target=server)
    try:
        assert conn.connect() == (True, '')
        result = call(wrapper(conn, 'configure'), {'config': {'remote': True}})
        assert result.artifact['structured_content'] == {'remote': True}
    finally:
        conn.disconnect()


def test_missing_optional_sdk_fails_without_hanging(monkeypatch):
    import builtins
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == 'fastmcp':
            raise ImportError('MCP extra not installed')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', importing)
    conn = MCPConnection('missing', '', {}, 2, 2, 20000)
    ok, error = conn.connect()
    assert not ok and 'extra not installed' in error
    assert not conn._thread.is_alive()


def test_disconnect_joins_worker_after_loop_closed():
    class ThreadStub:
        joined = False

        def is_alive(self):
            return not self.joined

        def join(self, timeout=None):
            self.joined = True

    conn = MCPConnection('closed', '', {}, 2, 2, 20000)
    conn._thread = ThreadStub()
    conn._loop = SimpleNamespace(is_running=lambda: False)
    conn.disconnect()
    assert conn._thread.joined


@pytest.mark.parametrize('server_count', [1, 2])
def test_protocol_helpers_do_not_displace_existing_tools_at_cap(server_count):
    from agent.mcp.manager import MCPManager
    from agent.mcp.client import ToolInfo
    manager = MCPManager.__new__(MCPManager)
    manager.max_tools = 100
    remotes = [ToolInfo(f'tool{i}', input_schema={'type': 'object', 'properties': {}}) for i in range(100)]
    def conn():
        return SimpleNamespace(status='connected', capabilities={'resources': {}}, list_tools=lambda: remotes,
            native_tools={tool.name: SimpleNamespace(metadata=None) for tool in remotes})
    manager._connections = dict(list({'first': conn(), 'second': conn()}.items())[:server_count])
    tools = manager.get_langchain_tools()
    assert len(tools) == 100 * server_count
    assert sum(tool.name.startswith('mcp__first__') for tool in tools) == 100
    assert sum(tool.name.startswith('mcp__second__') for tool in tools) == 100 * (server_count - 1)
