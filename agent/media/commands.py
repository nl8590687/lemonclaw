"""命令行与飞书共用的显式图片选择命令。"""
from pathlib import Path
import shlex
import shutil

from config import get_global_config
from dao.attachment import AttachmentDAO
from agent.media.images import register_image, image_message


def is_media_command(text):
    return (text.strip().split(maxsplit=1) or [''])[0].lower() in {'/image', '/upload'}


def copy_upload(path, context):
    if (context.get('source') or 'terminal') != 'terminal':
        raise ValueError('请使用附件编号；本地路径仅供命令行使用')
    from channels.device.feishu import received_dir, unique_path, safe_filename
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= 30 * 1024 * 1024:
        raise ValueError('上传文件为空或超过 30 MiB 限制')
    destination = unique_path(received_dir(), safe_filename(path.name, 'upload'))
    shutil.copyfile(path, destination)
    try:
        return register_image({'path': str(destination)}, context)
    except ValueError:
        return {'path': str(destination), 'name': destination.name, 'kind': '文件'}


def media_command(text, context):
    """返回 (用户问题, 选中附件, 回执)；上传/用法回执不进入模型。"""
    tokens = shlex.split(text)
    cmd = tokens.pop(0).lower()
    if '--' in tokens:
        boundary = tokens.index('--')
        selectors, question = tokens[:boundary], ' '.join(tokens[boundary + 1:])
    else:
        selectors, question = tokens, '请描述所选图片'
    dao = AttachmentDAO()
    if cmd == '/image' and not getattr(get_global_config(), 'ENABLE_VISION', True):
        raise ValueError('视觉能力未开启，请设置 ENABLE_VISION=True')
    if not selectors and cmd == '/image':
        return '', [], '用法：/image <图片编号或本地路径...|all> -- 问题；/upload [编号或本地路径...] 仅保存'
    if selectors == ['all'] or (not selectors and cmd == '/upload'):
        items = dao.pending(context)
    else:
        items = []
        for selector in selectors:
            if selector.startswith('img-'):
                items.append(dao.get(selector, context))
            else:
                item = copy_upload(selector, context)
                if cmd == '/image' and not item.get('attachment_id'):
                    raise ValueError(f'无法作为图片分析: {selector}')
                items.append(item)
    items = list({item.get('attachment_id', item['path']): item for item in items}.values())
    ids = [item['attachment_id'] for item in items if item.get('attachment_id')]
    if cmd == '/upload':
        dao.mark(ids, context, 'stored')
        if context.get('source') == 'feishu':
            from channels.device.feishu import discard_pending_images
            discard_pending_images(context.get('open_id'), context.get('chat_id'),
                                   None if not selectors or selectors == ['all'] else ids)
        return '', [], '仅保存：\n' + ('\n'.join(f"{item.get('attachment_id', '文件')} {item['name']} → {item['path']}" for item in items) or '没有暂存图片')
    image_message(question, ids, context)  # 在进入 Agent/checkpoint 前校验整个批次。
    return question, [dict(item, vision_selected=True) for item in items], None
