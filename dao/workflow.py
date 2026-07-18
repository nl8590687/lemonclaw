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
多 Agent 工作流（Workflow）数据模型与 DAO

存储在全局唯一的 sqlite 数据库 ``.lemonclaw/lemonclaw.db`` 中，
表名为 ``workflows``（工作流定义）与 ``workflow_runs``（运行实例）。
工作流 run 的 LangGraph checkpoint 由 ``SqliteSaver`` 存于同一库的
``checkpoints``/``writes`` 表（langgraph 自管）。
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dao.db import get_connection


# ============ 模型 ============

@dataclass
class Workflow:
    """工作流定义（声明式 spec）"""
    workflow_id: str                              # 主键，同时作 run 的 thread_id 前缀
    name: str                                      # 人可读名（唯一索引）
    description: str = ""
    spec: dict[str, Any] = field(default_factory=dict)   # {state_schema, nodes, edges, conditionals}
    version: int = 1                               # 每次保存递增
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_error: str | None = None                  # 最近编译错误

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "spec": self.spec,
            "version": self.version,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_error": self.last_error,
        }


@dataclass
class WorkflowRun:
    """工作流运行实例（= LangGraph thread）"""
    run_id: str                                    # 主键 = LangGraph thread_id
    workflow_id: str
    workflow_version: int                          # 启动时绑定版本
    status: str = "running"                        # running|paused|completed|error|cancelled
    loop_kind: str | None = None                   # paused 时中断类型 need_human|need_main_agent
    interrupt_info: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    origin_context: dict[str, Any] = field(default_factory=dict)   # 发起通道上下文（飞书 chat_id 等，HITL 通知路由用）
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "loop_kind": self.loop_kind,
            "interrupt_info": self.interrupt_info,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "origin_context": self.origin_context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ============ Schema ============

_WORKFLOW_DDL = """
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT NOT NULL DEFAULT '',
    spec          TEXT NOT NULL DEFAULT '{}',
    version       INTEGER NOT NULL DEFAULT 1,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL,
    last_error    TEXT
)
"""
_WORKFLOW_RUN_DDL = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id           TEXT PRIMARY KEY,
    workflow_id      TEXT NOT NULL,
    workflow_version INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'running',
    loop_kind        TEXT,
    interrupt_info   TEXT NOT NULL DEFAULT '{}',
    input            TEXT NOT NULL DEFAULT '{}',
    output           TEXT NOT NULL DEFAULT '{}',
    error            TEXT,
    origin_context   TEXT NOT NULL DEFAULT '{}',
    created_at       TIMESTAMP NOT NULL,
    updated_at       TIMESTAMP NOT NULL,
    completed_at     TIMESTAMP,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id) ON DELETE CASCADE
)
"""
_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_wf_enabled ON workflows(enabled)",
    "CREATE INDEX IF NOT EXISTS idx_wfr_workflow ON workflow_runs(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_wfr_status ON workflow_runs(status)",
]


def ensure_workflow_schema() -> None:
    """确保 workflows / workflow_runs 表与索引存在（幂等）。"""
    with get_connection() as conn:
        conn.execute(_WORKFLOW_DDL)
        conn.execute(_WORKFLOW_RUN_DDL)
        for ddl in _INDEX_DDL:
            conn.execute(ddl)


# ============ 辅助 ============

def _json_loads(raw, default):
    """安全 JSON 解析，失败返回 default"""
    if not raw:
        return default
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return default


def _row_to_workflow(row: sqlite3.Row) -> Workflow:
    return Workflow(
        workflow_id=row["workflow_id"],
        name=row["name"],
        description=row["description"] or "",
        spec=_json_loads(row["spec"], {}),
        version=row["version"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_error=row["last_error"],
    )


def _row_to_run(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        run_id=row["run_id"],
        workflow_id=row["workflow_id"],
        workflow_version=row["workflow_version"],
        status=row["status"],
        loop_kind=row["loop_kind"],
        interrupt_info=_json_loads(row["interrupt_info"], {}),
        input=_json_loads(row["input"], {}),
        output=_json_loads(row["output"], {}),
        error=row["error"],
        origin_context=_json_loads(row["origin_context"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


# ============ DAO ============

class WorkflowDAO:
    """工作流 SQL CRUD 操作"""

    def __init__(self):
        ensure_workflow_schema()

    # ---- Workflow ----

    def upsert_workflow(self, wf: Workflow) -> bool:
        """upsert 工作流定义（version 由调用方在保存前 +=1）。
        ON CONFLICT(workflow_id) DO UPDATE 覆盖 name/description/spec/version/enabled，
        保留 created_at。"""
        sql = """
        INSERT INTO workflows (workflow_id, name, description, spec, version, enabled, created_at, updated_at, last_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(workflow_id) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            spec = excluded.spec,
            version = excluded.version,
            enabled = excluded.enabled,
            updated_at = excluded.updated_at,
            last_error = excluded.last_error
        """
        params = (
            wf.workflow_id,
            wf.name,
            wf.description or "",
            json.dumps(wf.spec or {}, ensure_ascii=False),
            wf.version,
            1 if wf.enabled else 0,
            wf.created_at,
            datetime.now(),
            wf.last_error,
        )
        try:
            with get_connection() as conn:
                conn.execute(sql, params)
            return True
        except sqlite3.IntegrityError:
            return False

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
        return _row_to_workflow(row) if row else None

    def get_workflow_by_name(self, name: str) -> Workflow | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE name = ?", (name,)).fetchone()
        return _row_to_workflow(row) if row else None

    def list_workflows(self, include_disabled: bool = True) -> list[Workflow]:
        sql = "SELECT * FROM workflows" + ("" if include_disabled else " WHERE enabled = 1") + " ORDER BY updated_at DESC"
        with get_connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [_row_to_workflow(r) for r in rows]

    def set_last_error(self, workflow_id: str, err: str | None) -> bool:
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE workflows SET last_error = ?, updated_at = ? WHERE workflow_id = ?",
                (err, datetime.now(), workflow_id))
            return cursor.rowcount > 0

    def delete_workflow(self, workflow_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM workflows WHERE workflow_id = ?", (workflow_id,))
            return cursor.rowcount > 0

    # ---- WorkflowRun ----

    def create_run(self, run: WorkflowRun) -> bool:
        sql = """
        INSERT INTO workflow_runs (
            run_id, workflow_id, workflow_version, status, loop_kind,
            interrupt_info, input, output, error, origin_context,
            created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            run.run_id, run.workflow_id, run.workflow_version, run.status, run.loop_kind,
            json.dumps(run.interrupt_info or {}, ensure_ascii=False),
            json.dumps(run.input or {}, ensure_ascii=False),
            json.dumps(run.output or {}, ensure_ascii=False),
            run.error,
            json.dumps(run.origin_context or {}, ensure_ascii=False),
            run.created_at, run.updated_at, run.completed_at,
        )
        try:
            with get_connection() as conn:
                conn.execute(sql, params)
            return True
        except sqlite3.IntegrityError:
            return False

    def get_run(self, run_id: str) -> WorkflowRun | None:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, workflow_id: str | None = None, status: str | None = None,
                  limit: int = 50) -> list[WorkflowRun]:
        """列出 run。status: None=all, 'active'=running+paused, 或具体状态。"""
        clauses = []
        params: list = []
        if workflow_id:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if status:
            if status == "active":
                clauses.append("status IN ('running', 'paused')")
            else:
                clauses.append("status = ?")
                params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM workflow_runs{where} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_run(r) for r in rows]

    def list_pending_runs(self) -> list[WorkflowRun]:
        """返回 status=paused 的 run（重启后续跑扫描用）。"""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_runs WHERE status = 'paused' ORDER BY updated_at DESC").fetchall()
        return [_row_to_run(r) for r in rows]

    def update_run_status(self, run_id: str, status: str,
                          loop_kind: str | None = None,
                          interrupt_info: dict | None = None,
                          output: dict | None = None,
                          error: str | None = None,
                          completed_at: datetime | None = None) -> bool:
        """更新 run 状态与相关字段（仅更新非 None 的字段，status 必填）。"""
        sets = ["status = ?", "updated_at = ?"]
        params: list = [status, datetime.now()]
        if loop_kind is not None:
            sets.append("loop_kind = ?")
            params.append(loop_kind)
        if interrupt_info is not None:
            sets.append("interrupt_info = ?")
            params.append(json.dumps(interrupt_info, ensure_ascii=False))
        if output is not None:
            sets.append("output = ?")
            params.append(json.dumps(output, ensure_ascii=False))
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if completed_at is not None:
            sets.append("completed_at = ?")
            params.append(completed_at)
        params.append(run_id)
        sql = f"UPDATE workflow_runs SET {', '.join(sets)} WHERE run_id = ?"
        with get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount > 0

    def delete_run(self, run_id: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM workflow_runs WHERE run_id = ?", (run_id,))
            return cursor.rowcount > 0