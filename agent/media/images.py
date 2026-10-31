"""图片落盘引用与请求副本构造，原始字节只在发送时编码。"""
import base64
import hashlib
import io
from pathlib import Path
import warnings

from PIL import Image
from langchain_core.messages import HumanMessage

from dao.attachment import AttachmentDAO, attachment_scope

MAX_IMAGES = 8
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ENCODED_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIME = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'GIF': 'image/gif', 'WEBP': 'image/webp'}
REFS = 'lemonclaw_images'


def inspect_image(path):
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
        raise ValueError(f'图片为空或超过单图 10 MiB 限制: {path.name}')
    with path.open('rb') as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f'图片超过大小限制: {path.name}')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                mime = MIME.get(image.format)
                if mime is None or image.width * image.height > MAX_PIXELS:
                    raise ValueError('不支持的格式或像素数过大')
                width, height = image.size
                image.verify()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as ex:
        raise ValueError(f'图片损坏或格式不支持: {path.name}') from ex
    return {'path': str(path), 'name': path.name, 'type': 'image', 'kind': '图片',
            'size': len(data), 'mime_type': mime, 'width': width, 'height': height,
            'sha256': hashlib.sha256(data).hexdigest()}, data


def register_image(attachment, context, index=0):
    from config import get_global_config
    metadata, _ = inspect_image(attachment['path'])
    metadata['message_id'] = attachment.get('message_id')
    metadata['original_name'] = attachment.get('name') or metadata['name']
    item = AttachmentDAO().register(metadata, context, index,
        getattr(get_global_config(), 'FEISHU_PENDING_FILE_TTL_SECONDS', 1800))
    if item['sha256'] != metadata['sha256']:
        raise ValueError('同一消息的图片内容已变更')
    return item


def image_message(text, ids, context):
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > MAX_IMAGES:
        raise ValueError('请选择 1 至 8 张图片')
    dao = AttachmentDAO()
    refs, total = [], 0
    for aid in ids:
        item = dao.get(aid, context)
        actual, _ = inspect_image(item['path'])
        if actual['sha256'] != item['sha256']:
            raise ValueError(f'图片已变更: {aid}')
        total += actual['size']
        refs.append({'attachment_id': aid, 'scope': attachment_scope(context), 'sha256': item['sha256']})
    if total > MAX_TOTAL_BYTES:
        raise ValueError('图片总大小超过 20 MiB 限制')
    labels = '\n'.join(f'图{i + 1}（{ref["attachment_id"]}）' for i, ref in enumerate(refs))
    return HumanMessage(content=(text or '请描述所选图片') + '\n' + labels,
                        additional_kwargs={REFS: refs})


def check_image_scope(messages, context):
    """共享旧会话遇到其他来源图片时明确停止，避免跨来源读取图像。"""
    scope = attachment_scope(context)
    if any(ref.get('scope') != scope for msg in messages for ref in msg.additional_kwargs.get(REFS, [])):
        raise ValueError('当前历史包含其他来源的图片，请使用独立 session_key 或 /clear 清理共享历史')


def adapt_messages(messages, enabled):
    """保持 checkpoint 中消息不变，在请求副本中展开已校验附件引用。"""
    import json
    result, count, total, encoded = [], 0, 0, 0
    for msg in messages:
        refs = msg.additional_kwargs.get(REFS, [])
        if not refs:
            result.append(msg)
            continue
        if not enabled:
            result.append(msg.model_copy(update={'content': str(msg.content) + '\n[视觉功能关闭，仅保留图片引用，未提供图片内容]'}))
            continue
        if not isinstance(msg, HumanMessage):
            raise ValueError('图片引用只支持用户消息')
        content = [{'type': 'text', 'text': str(msg.content)}]
        for ref in refs:
            count += 1
            if count > MAX_IMAGES:
                raise ValueError('本次上下文图片超过 8 张，请先归档历史或清理会话')
            scope = json.loads(ref['scope'])
            context = dict(zip(('source', 'chat_id', 'open_id', 'session_key'), scope))
            item = AttachmentDAO().get(ref['attachment_id'], context)
            actual, data = inspect_image(item['path'])
            if actual['sha256'] != ref['sha256'] or actual['sha256'] != item['sha256']:
                raise ValueError(f'图片已变更: {ref["attachment_id"]}')
            total += len(data)
            b64 = base64.b64encode(data).decode('ascii')
            encoded += len(b64)
            if total > MAX_TOTAL_BYTES or encoded > MAX_ENCODED_BYTES:
                raise ValueError('上下文图片超过请求大小限制')
            content.extend([{'type': 'text', 'text': f'图片 {ref["attachment_id"]}'},
                            {'type': 'image_url', 'image_url': {'url': f'data:{actual["mime_type"]};base64,{b64}'}}])
        result.append(msg.model_copy(update={'content': content}))
    return result, count > 0
