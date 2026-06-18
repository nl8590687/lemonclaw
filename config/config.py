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
    OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL", "")
    OPENAI_API_KEY: SecretStr = SecretStr(os.environ.get("OPENAI_API_KEY", ""))
    MODEL_NAME: str = os.environ.get("MODEL_NAME", "")
    MODEL_CONTEXT_LENGTH: int = int(os.environ.get("MODEL_CONTEXT_LENGTH", 128000))
    MODEL_MAX_COMPLETION_TOKEN: int = int(os.environ.get("MODEL_MAX_COMPLETION_TOKEN", 128000))
    TEMPERATURE: float = float(os.environ.get("TEMPERATURE", 0.7))
    LLM_API_TIMEOUT: int = int(os.environ.get("LLM_API_TIMEOUT", 60))

    BOCHA_API_URL: str|None = os.environ.get("BOCHA_API_URL")
    BOCHA_API_KEY: str|None = os.environ.get("BOCHA_API_KEY")

    EMAIL_SMTP_SERVER: str|None = os.environ.get("EMAIL_SMTP_SERVER")
    EMAIL_SMTP_ENCRYPTION: str|None = os.environ.get("EMAIL_SMTP_ENCRYPTION", "SSL")
    EMAIL_SMTP_PORT: int = int(os.environ.get("EMAIL_SMTP_PORT", 465))
    EMAIL_SMTP_USERNAME: str|None = os.environ.get("EMAIL_SMTP_USERNAME")
    EMAIL_SMTP_PASSWORD: str|None = os.environ.get("EMAIL_SMTP_PASSWORD")
    EMAIL_FROM_NAME: str|None = os.environ.get("EMAIL_FROM_NAME", "LemonClaw")

    ENABLE_BASH_TOOL: bool = str(os.environ.get("ENABLE_BASH_TOOL", "false")).lower() == "true"
    FILE_SAFE_DIRS: str = str(os.environ.get("FILE_SAFE_DIRS", ""))

    AGENT_REACT_MAX_ITERATIONS: int = int(os.environ.get("AGENT_REACT_MAX_ITERATIONS", 20))
    CONTEXT_MIN_FULL_MESSAGES: int = int(os.environ.get("CONTEXT_MIN_FULL_MESSAGES", 20))

    ENABLE_WEBHOOK: bool = str(os.environ.get("ENABLE_WEBHOOK", "false")).lower() == "true"
    WEBHOOK_HOST: str|None = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    WEBHOOK_PORT: int = int(os.environ.get("WEBHOOK_PORT", 8765))
    WEBHOOK_AUTH_TOKEN: str|None = os.environ.get("WEBHOOK_AUTH_TOKEN", "")
    WEBHOOK_RATE_LIMIT_RPM: int = int(os.environ.get("WEBHOOK_RATE_LIMIT_RPM", 10))


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
