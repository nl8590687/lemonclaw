import os
from pathlib import Path

from dotenv import load_dotenv
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
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    MODEL_NAME: str = os.environ.get("MODEL_NAME", "")
    MODEL_MAX_TOKEN: int = int(os.environ.get("MODEL_MAX_TOKEN", 128000))
    TEMPERATURE: float = float(os.environ.get("TEMPERATURE", 0.7))
    LLM_API_TIMEOUT: int = int(os.environ.get("LLM_API_TIMEOUT", 60))

    @classmethod
    def load(cls) -> "GlobalConfig":
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
        return cls()


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
        _global_config = GlobalConfig.load()
    return _global_config
