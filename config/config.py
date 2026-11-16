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

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings


def find_config_file(filename: str) -> Path|None:
    """
    按优先级查找配置文件：
    1. 当前工作目录下的 .lemonclaw/{filename}
    2. 项目安装的根目录下的 .lemonclaw/{filename}

    Params:
        filename: 要查找的配置文件名，如 ".env" 或 "config.yaml"

    Return:
        找到的配置文件路径，找不到返回 None
    """
    # 1. 当前工作目录的 .lemonclaw 下
    cwd_config = Path.cwd() / ".lemonclaw" / filename
    if cwd_config.exists():
        return cwd_config

    # 2. 项目安装的根目录下的 filename
    project_root = os.path.basename(Path(__file__))
    config_path = os.path.join(project_root, ".lemonclaw", filename)
    if os.path.exists(config_path):
        return Path(config_path)

    return None


class GlobalConfig(BaseSettings):
    """
    全局配置
    """
    OPENAI_BASE_URL: str = ''
    OPENAI_API_KEY: SecretStr = SecretStr('')
    ENABLE_VISION: bool = str('true').lower() == 'true'
    LLM_FALLBACK_ENABLE_VISION: bool = str('false').lower() == 'true'
    MODEL_NAME: str = ''
    MODEL_CONTEXT_LENGTH: int = int(128000)
    MODEL_MAX_COMPLETION_TOKEN: int = int(128000)
    TEMPERATURE: float = float(0.7)
    LLM_API_TIMEOUT: int = int(60)
    LLM_MAX_RETRIES: int = int(10)
    LLM_RETRY_BASE_DELAY: float = float(1)
    LLM_RETRY_MAX_DELAY: float = float(30)
    LLM_TOTAL_TIMEOUT: float = float(180)
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = int(3)
    LLM_CIRCUIT_COOLDOWN: float = float(30)
    LLM_FALLBACK_MODEL: str = ''
    LLM_FALLBACK_BASE_URL: str = ''
    LLM_FALLBACK_API_KEY: SecretStr = SecretStr('')

    # Web/HTTP 安全：私网/本地目标需当前用户 URL 授权或进入信任列表
    WEB_ACCESS_ALLOW_PRIVATE: bool = str('true').lower() == 'true'
    WEB_PRIVATE_ALLOWLIST: str = str('')
    WEB_ALLOW_PRIVATE_WRITES: bool = str('false').lower() == 'true'
    WEB_MAX_REDIRECTS: int = int(5)
    WEB_MAX_RESPONSE_BYTES: int = int(2000000)
    WEB_REQUEST_TIMEOUT: int = int(60)

    BOCHA_API_URL: str|None = None
    BOCHA_API_KEY: str|None = None

    EMAIL_SMTP_SERVER: str|None = None
    EMAIL_SMTP_ENCRYPTION: str|None = 'SSL'
    EMAIL_SMTP_PORT: int = int(465)
    EMAIL_SMTP_USERNAME: str|None = None
    EMAIL_SMTP_PASSWORD: str|None = None
    EMAIL_FROM_NAME: str|None = 'LemonClaw'

    ENABLE_BASH_TOOL: bool = str('false').lower() == 'true'
    FILE_SAFE_DIRS: str = str('')

    AGENT_REACT_MAX_ITERATIONS: int = int(20)
    CONTEXT_TOOL_MAX_CHARS: int = int(12000)
    CONTEXT_MIN_FULL_MESSAGES: int = int(20)

    ENABLE_WEBHOOK: bool = str('false').lower() == 'true'
    WEBHOOK_HOST: str|None = '127.0.0.1'
    WEBHOOK_PORT: int = int(8765)
    WEBHOOK_AUTH_TOKEN: str|None = ''
    WEBHOOK_RATE_LIMIT_RPM: int = int(10)

    # WebUI
    ENABLE_WEBUI: bool = True
    WEBUI_HOST: str = "127.0.0.1"
    WEBUI_PORT: int = 8080
    WEBUI_AUTH_KEY: SecretStr = SecretStr("")

    # 飞书（Lark）
    ENABLE_FEISHU: bool = str('false').lower() == 'true'
    FEISHU_APP_ID: str|None = ''
    FEISHU_APP_SECRET: SecretStr = SecretStr('')
    # 收到飞书文件/图片/音视频后的统一落盘目录
    FEISHU_RECEIVED_DIR: str = '/root/workspace/received'
    # 单文件大小上限（MB）。下载接口官方上限 100MB；上传接口文件上限 30MB
    FEISHU_MAX_DOWNLOAD_MB: int = int('100')
    FEISHU_MAX_SEND_FILE_MB: int = int('30')
    # 纯文件消息暂存等待用户补充文本的过期时间（秒）
    FEISHU_PENDING_FILE_TTL_SECONDS: int = int('1800')

    # 持久化记忆
    ENABLE_MEMORY: bool = str('true').lower() == 'true'
    MEMORY_MAX_CONTEXT_TOKENS: int = int(1500)
    MEMORY_RECENT_SESSIONS: int = int(3)
    MEMORY_MAX_SEARCH_CHUNKS: int = int(100)
    MEMORY_AUTO_ARCHIVE: bool = str('true').lower() == 'true'

    # Skills 技能系统
    ENABLE_SKILLS: bool = str('true').lower() == 'true'
    ENABLE_SKILL_SCRIPT: bool = str('false').lower() == 'true'
    MAX_ACTIVE_SKILLS: int = int(5)
    PIP_INDEX_URL: str = 'https://pypi.tuna.tsinghua.edu.cn/simple'
    NPM_REGISTRY: str = 'https://registry.npmmirror.com'
    SKILL_SCRIPT_TIMEOUT: int = int(120)

    # MCP 接入（仅 Streamable HTTP）
    ENABLE_MCP: bool = str('true').lower() == 'true'
    MCP_CONNECT_TIMEOUT: int = int(30)
    MCP_CALL_TIMEOUT: int = int(300)
    MCP_MAX_TOOLS: int = int(100)
    MCP_RESULT_MAX_CHARS: int = int(20000)

    # 多 Agent 工作流（基于 LangGraph）
    ENABLE_WORKFLOW: bool = str('true').lower() == 'true'
    WORKFLOW_RECURSION_LIMIT: int = int(50)
    WORKFLOW_NESTING_MAX: int = int(5)
    WORKFLOW_MAX_NODES: int = int(50)
    WORKFLOW_MAX_BRANCHES: int = int(20)
    WORKFLOW_RESULT_MAX_CHARS: int = int(20000)
    WORKFLOW_WORKER_POOL_SIZE: int = int(4)
    WORKFLOW_HITL_DEFAULT_HANDLER: str = 'interactive'


def load_config() -> GlobalConfig:
    """
    从配置文件和环境变量加载配置

    Return:
        配置对象
    """
    # 首先加载 .env

    env_path = find_config_file(".env")
    if env_path and env_path.exists():
        load_dotenv(env_path)

    # 创建配置对象，YAML 配置会覆盖默认值，环境变量会覆盖 YAML
    return GlobalConfig()


# 全局配置实例（延迟加载）
_global_config: GlobalConfig|None = None


def get_global_config() -> GlobalConfig:
    """
    获取全局配置实例（单例）

    Returns:
        全局配置对象
    """
    global _global_config
    if _global_config is None:
        _global_config = load_config()
    return _global_config
