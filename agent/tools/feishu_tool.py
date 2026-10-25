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

"""飞书文件发送工具。"""

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from channels.device.feishu import (
    FeishuMessageSender,
    get_feishu_client,
    get_feishu_owner_open_id,
)
from config import get_global_config


@dataclass(frozen=True)
class FeishuTurn:
    """当前轮次的飞书投递目标。"""

    open_id: str | None
    chat_id: str | None
    chat_type: str | None


_current_turn: ContextVar[FeishuTurn | None] = ContextVar(
    "lemonclaw_feishu_turn", default=None
)


def begin_feishu_turn(context: dict[str, Any] | None):
    """从事件 context 记录本轮飞书会话，返回 ContextVar token。"""
    if not isinstance(context, dict) or context.get("source") != "feishu":
        return None
    turn = FeishuTurn(
        open_id=context.get("open_id") if isinstance(context.get("open_id"), str) else None,
        chat_id=context.get("chat_id") if isinstance(context.get("chat_id"), str) else None,
        chat_type=context.get("chat_type") if isinstance(context.get("chat_type"), str) else None,
    )
    return _current_turn.set(turn)


def reset_feishu_turn(token) -> None:
    if token is not None:
        _current_turn.reset(token)


def get_feishu_turn() -> FeishuTurn | None:
    return _current_turn.get()


class FeishuSendFileInput(BaseModel):
    """飞书文件发送工具输入。"""

    path: str = Field(description="要发送的文件路径，必须位于工作空间或 FILE_SAFE_DIRS 内")


def feishu_enabled(config: Any) -> bool:
    """飞书机器人配置完整时才注册飞书工具。"""
    secret = getattr(config, "FEISHU_APP_SECRET", "")
    if hasattr(secret, "get_secret_value"):
        secret = secret.get_secret_value()
    return bool(getattr(config, "ENABLE_FEISHU", False) and getattr(config, "FEISHU_APP_ID", "") and secret)


def _create_sender() -> FeishuMessageSender:
    client = get_feishu_client()
    if client is not None:
        return client.sender
    return FeishuMessageSender()


class FeishuSendFileTool(BaseTool):
    """把工作空间中的文件发送给飞书用户。"""

    name: str = "feishu_send_file"
    description: str = (
        "把工作空间中的指定文件发送给飞书用户。支持普通文件、图片、音频和 MP4 视频；"
        "仅在启用飞书机器人接入后可用。"
    )
    args_schema: Type[BaseModel] = FeishuSendFileInput
    model_config = {"extra": "allow"}

    def __init__(self, safe_dirs: list[str]):
        super().__init__()
        self._safe_dirs = [str(Path(item).resolve()) for item in safe_dirs if str(item).strip()]
        if not self._safe_dirs:
            self._safe_dirs = [str(Path.cwd().resolve())]

    def _run(self, *args, **kwargs) -> str:
        path: Optional[str] = None

        if args:
            first = args[0]
            if isinstance(first, dict):
                path = first.get("path")
            elif isinstance(first, str):
                try:
                    parsed = json.loads(first)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    path = parsed.get("path")
                else:
                    path = first
        path = path or kwargs.get("path")

        if not isinstance(path, str) or not path.strip():
            return self._error("missing_path", "必须提供文件路径参数 path")

        resolved, error = self._resolve_safe_file(path.strip())
        if error:
            return self._error(error[0], error[1])

        config = get_global_config()
        max_bytes = max(0, int(getattr(config, "FEISHU_MAX_SEND_FILE_MB", 30))) * 1024 * 1024
        size = resolved.stat().st_size
        if size == 0:
            return self._error("file_empty", "文件为空，飞书不接受 0 字节文件")
        if max_bytes and size > max_bytes:
            return self._error(
                "file_too_large",
                f"文件大小 {size} 字节，超过配置上限 {max_bytes // (1024 * 1024)}MB",
            )

        receive_id, receive_id_type = self._resolve_recipient()
        if not receive_id:
            return self._error(
                "missing_recipient",
                "无法确定飞书接收人：请先在飞书中给机器人发送一条消息完成绑定",
            )

        try:
            sender = _create_sender()
            result = sender.send_file(str(resolved), receive_id, receive_id_type)
        except ImportError as exc:
            return self._error("feishu_unavailable", str(exc))
        except Exception as exc:
            return self._error("send_failed", str(exc))

        return json.dumps(
            {
                "success": True,
                "path": str(resolved),
                "size": size,
                "msg_type": result.get("msg_type"),
                "degraded": bool(result.get("degraded", False)),
                "message_id": result.get("message_id"),
                "receiver": {"id": receive_id, "id_type": receive_id_type},
            },
            ensure_ascii=False,
        )

    def _resolve_safe_file(self, path: str) -> tuple[Path | None, tuple[str, str] | None]:
        """校验文件存在、非符号链接且位于安全目录内。"""
        target = Path(path).expanduser()
        if target.is_symlink() or os.path.islink(str(target)):
            return None, ("unsafe_path", "不允许发送符号链接文件")
        try:
            resolved = target.resolve()
        except Exception as exc:
            return None, ("invalid_path", f"路径解析失败: {exc}")
        if resolved.is_symlink() or os.path.islink(str(resolved)):
            return None, ("unsafe_path", "不允许发送符号链接文件")
        if self._is_sensitive_path(resolved):
            return None, ("sensitive_path", "不允许发送配置、密钥或数据库文件")

        for safe_dir in self._safe_dirs:
            try:
                if os.path.commonpath([safe_dir, str(resolved)]) == safe_dir:
                    break
            except ValueError:
                continue
        else:
            return None, ("unsafe_path", f"路径不在允许的安全目录列表中: {self._safe_dirs}")

        if not resolved.exists():
            return None, ("not_found", f"文件不存在: {resolved}")
        if not resolved.is_file():
            return None, ("not_a_file", f"目标不是普通文件: {resolved}")
        return resolved, None

    @staticmethod
    def _is_sensitive_path(resolved: Path) -> bool:
        lowered_parts = {part.lower() for part in resolved.parts}
        if ".lemonclaw" in lowered_parts:
            return True
        name = resolved.name.lower()
        if name == ".env" or name.startswith(".env."):
            return True
        if name in {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}:
            return True
        return resolved.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".db"}

    @staticmethod
    def _resolve_recipient() -> tuple[str | None, str]:
        turn = get_feishu_turn()
        if turn is not None:
            if turn.chat_type and turn.chat_type != "p2p" and turn.chat_id:
                return turn.chat_id, "chat_id"
            if turn.open_id:
                return turn.open_id, "open_id"

        owner_open_id = get_feishu_owner_open_id()
        return (owner_open_id, "open_id") if owner_open_id else (None, "open_id")

    @staticmethod
    def _error(code: str, message: str) -> str:
        return json.dumps(
            {"success": False, "error": message, "code": code},
            ensure_ascii=False,
        )


def create_feishu_send_file_tool(safe_dirs: list[str]) -> FeishuSendFileTool:
    """创建飞书文件发送工具。"""
    return FeishuSendFileTool(safe_dirs)
