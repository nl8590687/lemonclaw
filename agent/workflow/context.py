"""从运行配置提取 Workflow 回调的来源信息。"""

from langchain_core.runnables import RunnableConfig

_ORIGIN_FIELDS = ('source', 'channel', 'open_id', 'chat_id', 'chat_type',
                  'session_key', 'task_id', 'cron_expression')


def origin_context(config: RunnableConfig | None) -> dict:
    context = (config or {}).get('configurable', {}).get('origin_context', {})
    if not isinstance(context, dict):
        return {}
    return {key: context[key] for key in _ORIGIN_FIELDS
            if isinstance(context.get(key), str)}
