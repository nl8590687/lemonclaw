import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from channels.device import feishu
from lark_oapi.core.token.manager import TokenManager
from agent.tools.bash_tool import BashTool


def python_command(code):
    """使用与 BashTool 相同的平台 shell，正确引用当前 Python 路径。"""
    argv = [sys.executable, '-c', code]
    if sys.platform.startswith('win'):
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr(feishu, 'get_global_config', lambda: SimpleNamespace(
        FEISHU_APP_ID='test-app', FEISHU_APP_SECRET=SecretStr('test-secret')))
    sender = Mock()
    monkeypatch.setattr(feishu, 'FeishuMessageSender', Mock(return_value=sender))
    token = Mock(return_value='test-token')
    monkeypatch.setattr(TokenManager, 'get_self_tenant_token', token)
    return token


def test_child_environment_preserves_parent_and_refreshes(credentials):
    parent = {'PATH': '/bin', 'CUSTOM': 'kept'}
    first = feishu.bash_cli_environment(parent)
    credentials.return_value = 'new-token'
    second = feishu.bash_cli_environment(parent)
    assert parent == {'PATH': '/bin', 'CUSTOM': 'kept'}
    assert first['CUSTOM'] == 'kept'
    assert first['LARKSUITE_CLI_APP_ID'] == 'test-app'
    assert first['LARKSUITE_CLI_APP_SECRET'] == 'test-secret'
    assert first['LARKSUITE_CLI_BRAND'] == 'feishu'
    assert first['LARKSUITE_CLI_TENANT_ACCESS_TOKEN'] == 'test-token'
    assert second['LARKSUITE_CLI_TENANT_ACCESS_TOKEN'] == 'new-token'


def test_bridge_profile_is_not_overridden(credentials):
    parent = {'LARK_CHANNEL': '1', 'LARKSUITE_CLI_CONFIG_DIR': '/bound'}
    assert feishu.bash_cli_environment(parent) == parent
    credentials.assert_not_called()


def test_unconfigured_environment_is_unchanged(monkeypatch):
    monkeypatch.setattr(feishu, 'get_global_config', lambda: SimpleNamespace(
        FEISHU_APP_ID='', FEISHU_APP_SECRET=SecretStr('')))
    assert feishu.bash_cli_environment({'CUSTOM': 'kept'}) == {'CUSTOM': 'kept'}


def test_token_failure_does_not_expose_sdk_error(credentials):
    credentials.side_effect = ValueError('test-secret')
    with pytest.raises(RuntimeError, match='应用身份初始化失败') as error:
        feishu.bash_cli_environment({})
    assert 'test-secret' not in str(error.value)


def test_bash_receives_child_environment(monkeypatch):
    monkeypatch.setattr(feishu, 'bash_cli_environment', lambda env: {**env, 'CLI_TEST': 'injected'})
    result = BashTool()._run(python_command('import os; print(os.environ["CLI_TEST"])'))
    assert 'injected' in result
    assert '退出代码: 0' in result


def test_bash_redacts_cli_secrets(monkeypatch):
    monkeypatch.setattr(feishu, 'bash_cli_environment', lambda env: {
        **env, 'LARKSUITE_CLI_APP_SECRET': 'private-secret',
        'LARKSUITE_CLI_TENANT_ACCESS_TOKEN': 'private-token'})
    result = BashTool()._run(python_command(
        'import os; print(os.environ["LARKSUITE_CLI_APP_SECRET"], '
        'os.environ["LARKSUITE_CLI_TENANT_ACCESS_TOKEN"])'))
    assert 'private-secret' not in result
    assert 'private-token' not in result
    assert '[REDACTED]' in result
