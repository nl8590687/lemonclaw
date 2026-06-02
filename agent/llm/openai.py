from langchain_openai import ChatOpenAI

from config import get_global_config


def create_openai_llm() -> ChatOpenAI:
    """
    根据配置创建 OpenAI兼容的LLM 实例
    """
    global_config = get_global_config()
    return ChatOpenAI(
        model=global_config.MODEL_NAME,
        temperature=global_config.TEMPERATURE,
        max_tokens=global_config.MODEL_MAX_TOKEN,
        streaming=True,
        stream_usage=True,
        base_url=global_config.OPENAI_BASE_URL,
        api_key=global_config.OPENAI_API_KEY,
        timeout=global_config.LLM_API_TIMEOUT,
        max_retries=3
    )
