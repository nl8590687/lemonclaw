"""飞书用户请求的本轮处理状态；表情失败不影响主流程。"""
from langchain_core.messages import AIMessage

from config import get_global_config


def reaction_eligible(context):
    return (getattr(get_global_config(), 'ENABLE_FEISHU', False)
            and context.get('source') == 'feishu'
            and context.get('sender_type') == 'user'
            and isinstance(context.get('message_id'), str) and bool(context['message_id']))


def turn_completed(result):
    messages = result.get('messages', []) if isinstance(result, dict) else []
    return bool(messages and isinstance(messages[-1], AIMessage)
                and isinstance(messages[-1].content, str) and messages[-1].content.strip())


def finish_reaction(context, sender, completed):
    if not context.pop('feishu_reaction_active', False):
        return
    reaction_id = context.pop('feishu_typing_reaction_id', None)
    try:
        if reaction_id:
            sender.delete_reaction(context['message_id'], reaction_id)
        if completed:
            sender.add_reaction(context['message_id'], 'DONE')
    except Exception:
        # 对测试替身或第三方 sender 同样隔离异常。
        import logging
        logging.getLogger(__name__).warning('飞书状态表情更新失败，主流程继续')


def finish_live_reaction(context, completed):
    try:
        from channels.device.feishu import get_feishu_client
        client = get_feishu_client()
        if client is not None:
            finish_reaction(context, client.sender, completed)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('飞书状态表情清理失败，主流程继续')
