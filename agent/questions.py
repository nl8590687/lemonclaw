"""人工问题的校验、终端协议与主轮次上下文。"""
from contextvars import ContextVar
from typing import Literal
from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=300)
    kind: Literal['single', 'multiple', 'text'] = 'single'
    options: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode='after')
    def validate_options(self):
        self.options = [s.strip() for s in self.options]
        if self.kind == 'text' and self.options:
            raise ValueError('文本题不能设置选项')
        if self.kind != 'text' and (not self.options or any(not s or len(s) > 80 for s in self.options)
                                    or len(set(self.options)) != len(self.options)):
            raise ValueError('选择题需要 1–12 个非空且不重复的选项，每项最多 80 字')
        return self


class QuestionSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=1500)
    questions: list[UserQuestion] = Field(min_length=1, max_length=8)
    timeout_seconds: int = Field(default=3600, ge=1200, le=86400, strict=True)


def actor_matches(row, context):
    origin = row['origin']
    source = context.get('source') or 'terminal'
    expected = origin.get('source') or 'terminal'
    expected_event = 'lark_message' if expected == 'feishu' else 'terminal'
    if source != expected or context.get('_event_type') not in {None, '', expected_event}:
        return False
    if expected == 'feishu':
        return (context.get('sender_type') == 'user' and context.get('open_id') == origin.get('open_id')
                and (not origin.get('chat_id') or context.get('chat_id') == origin['chat_id']))
    return expected == 'terminal'


def validate_answers(spec, fields):
    answers = []
    for i, question in enumerate(spec['questions'], 1):
        raw = fields.get(str(i))
        if question['kind'] == 'text':
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 1000:
                raise ValueError(f'第 {i} 题请输入 1–1000 字文本')
            answers.append({'question': question['prompt'], 'values': [raw.strip()]})
            continue
        if not isinstance(raw, list) or not raw:
            raise ValueError(f'第 {i} 题请选择选项')
        values = [str(x).strip() for x in raw]
        if len(set(values)) != len(values) or (question['kind'] == 'single' and len(values) != 1):
            raise ValueError(f'第 {i} 题选项重复或单选数量不正确')
        if '0' in values:
            other = fields.get(f'{i}_other', '')
            if len(values) != 1 or not isinstance(other, str) or not other.strip() or len(other) > 1000:
                raise ValueError(f'第 {i} 题选“以上均不是”时须单独选择并填写文本')
            selected = [other.strip()]
        else:
            if any(not v.isascii() or not v.isdecimal() or not 1 <= int(v) <= len(question['options']) for v in values):
                raise ValueError(f'第 {i} 题选项序号无效')
            selected = [question['options'][int(v)-1] for v in values]
        answers.append({'question': question['prompt'], 'values': selected})
    result = {'status': 'confirmed', 'action': 'continue', 'answers': answers}
    if '_mcp_requests' in spec:
        from agent.mcp.elicitation import validate_mcp_answers
        validate_mcp_answers(spec, result)
    return result


def parse_terminal(spec, text):
    text = text.strip()
    if text == '/cancel':
        return {'status': 'cancelled', 'action': 'cancel', 'answers': []}
    questions = spec['questions']
    if len(questions) == 1 and questions[0]['kind'] != 'text':
        pairs = [('1', text)]
    else:
        # 仅在逗号后出现“题号:”时切分；普通文本中的逗号保留。
        parts = re.split(r'(?:[,，]|\n)\s*(?=\d+\s*[:：])', text)
        pairs = []
        for part in parts:
            match = re.fullmatch(r'\s*(\d+)\s*[:：]\s*(.*)', part, re.S)
            if not match:
                raise ValueError('请用“题号:回答”填写，例如 1:小明,2:28岁')
            pairs.append((match[1], match[2].strip()))
    fields = {}
    for key, value in pairs:
        if key in fields or not 1 <= int(key) <= len(questions):
            raise ValueError('题号重复或超出范围')
        question = questions[int(key)-1]
        if question['kind'] == 'text':
            fields[key] = value
        elif re.match(r'^0\s*[:：]', value):
            fields[key] = ['0']
            fields[f'{key}_other'] = re.split(r'[:：]', value, maxsplit=1)[1].strip()
        else:
            fields[key] = [x.strip() for x in re.split('[,，]', value)]
    return validate_answers(spec, fields)


def terminal_question(row):
    spec = row['payload']
    lines = ['请求用户确认', spec['reason'], f"问题编号：{row['question_id']}",
             f"截止时间：{datetime.fromtimestamp(row['deadline']).astimezone().isoformat(timespec='minutes')}；到期按取消处理。"]
    for i, question in enumerate(spec['questions'], 1):
        lines.append(f"{i}. {question['prompt']}（{question['kind']}）")
        lines.extend(f'  {j}. {option}' for j, option in enumerate(question['options'], 1))
        if question['kind'] != 'text':
            lines.append('  0. 以上均不是：输入 0:实际内容')
    lines.append('单个选择题：1 或 1,2；文本题：1:小明,2:28岁；多道选择题：1:1,2:2；/cancel 取消。')
    return '\n'.join(lines)


_question_turn: ContextVar[dict | None] = ContextVar('question_turn', default=None)


def begin_question_turn(context, input_text, session_key):
    return _question_turn.set({'context': context, 'input': input_text, 'session_key': session_key})


def reset_question_turn(token):
    _question_turn.reset(token)


def pending_question(state):
    for task in getattr(state, 'tasks', ()):
        for value in getattr(task, 'interrupts', ()):
            if isinstance(value.value, dict) and value.value.get('kind') == 'ask_user_question':
                return value.value['question_id']
    return None
