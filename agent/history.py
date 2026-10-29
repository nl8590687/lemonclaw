"""历史维护：保护最近消息及工具配对，仅缩短保留区外的超长内容。"""

from langchain_core.messages import AIMessage, ToolMessage


_TRIM_MARKER = "\n[历史超长内容已截断]\n"


def protected_boundary(messages, keep: int) -> int:
    """最近 keep 条为下限，向前扩展以保留完整工具调用/结果组。"""
    boundary = max(0, len(messages) - max(0, keep))
    calls = {call['id']: index for index, msg in enumerate(messages)
             if isinstance(msg, AIMessage) for call in msg.tool_calls}
    while True:
        earlier = [calls[msg.tool_call_id] for msg in messages[boundary:]
                   if isinstance(msg, ToolMessage) and msg.tool_call_id in calls
                   and calls[msg.tool_call_id] < boundary]
        if not earlier:
            return boundary
        boundary = min(earlier)


def _shorten(value, limit):
    if isinstance(value, str) and len(value) > limit:
        keep = (limit - len(_TRIM_MARKER)) // 2
        return value[:keep] + _TRIM_MARKER + value[-keep:]
    if isinstance(value, dict):
        return {key: _shorten(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_shorten(item, limit) for item in value]
    return value


def trim_oversized(messages, boundary: int, limit: int):
    """构造消息与参数副本，返回裁剪后的消息列表。"""
    if limit <= len(_TRIM_MARKER) + 2:
        raise ValueError('CONTEXT_TOOL_MAX_CHARS 过小')
    result = []
    for index, msg in enumerate(messages):
        if index < boundary and isinstance(msg, ToolMessage):
            if isinstance(msg.content, str):
                content = _shorten(msg.content, limit)
            else:
                # 只裁剪文本块，图片/音频等数据与引用保持原样。
                content = [{**block, 'text': _shorten(block['text'], limit)}
                           if isinstance(block, dict) and block.get('type') == 'text'
                           and isinstance(block.get('text'), str) else block
                           for block in msg.content]
            if content != msg.content:
                msg = msg.model_copy(update={'content': content})
        elif index < boundary and isinstance(msg, AIMessage) and msg.tool_calls:
            calls = [{**call, 'args': _shorten(call['args'], limit)} for call in msg.tool_calls]
            if calls != msg.tool_calls:
                msg = msg.model_copy(update={'tool_calls': calls})
        result.append(msg)
    return result
