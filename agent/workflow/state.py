#!/usr/bin/env python
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

"""
工作流状态 schema 构建与辅助

build_state_schema 据 spec 的 state_fields 动态构造 TypedDict（含 reducer）。
"""

import types
from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


# reducer 注册表（spec 用字符串引用）
REDUCERS = {
    "add_messages": add_messages,
    "overwrite": lambda l, r: r,
    "append": lambda l, r: (l or []) + [r],
}

# spec type -> Python 类型
TYPE_MAP = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "list": list,
    "dict": dict,
    "any": Any,
    "Any": Any,
}


def build_state_schema(state_fields: list[dict]) -> type:
    """据 spec 的 state_fields（[{name, type, reducer?}]）动态构造 TypedDict state schema。

    type: str/int/float/bool/list/dict/Any（默认 Any）；
    reducer: add_messages/overwrite/append/None（默认 None = overwrite 语义，但不挂 reducer）。
    用 types.new_class 动态组装 TypedDict（含 Annotated reducer）。
    """
    if not state_fields:
        # 无字段：返回最小 TypedDict（LangGraph 需要至少一个 schema）
        state_fields = [{"name": "_placeholder", "type": "str"}]

    annotations = {}
    for f in state_fields:
        name = f.get("name")
        if not name:
            continue
        py_type = TYPE_MAP.get(f.get("type", "Any"), Any)
        reducer = REDUCERS.get(f.get("reducer"))
        annotations[name] = Annotated[py_type, reducer] if reducer else py_type

    def exec_body(ns):
        ns["__annotations__"] = annotations
        ns["__required_keys__"] = frozenset(annotations.keys())
        ns["__optional_keys__"] = frozenset()

    return types.new_class("WorkflowState", (TypedDict,), exec_body=exec_body)


def render_template(template: str, state: dict) -> str:
    """简单 {var} 插值（取 state 字段）。支持 ${var} 和 {var} 两种语法。缺失字段保留原样。"""
    if not template:
        return ""
    # Support ${var} syntax (in addition to {var})
    if "${" in template:
        template = template.replace("${", "{")
    try:
        return template.format_map(_SafeDict(state or {}))
    except Exception:
        return template


class _SafeDict(dict):
    """format_map 时缺失 key 返回 {key} 原样，不抛 KeyError"""
    def __missing__(self, key):
        return "{" + key + "}"
