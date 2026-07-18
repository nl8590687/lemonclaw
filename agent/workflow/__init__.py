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
多 Agent 工作流业务层子包

模块：
- state.py     状态 schema 构建与模板插值
- nodes.py     内置节点实现（llm/tool/main_agent/subagent/human/subgraph）
- subagents.py BaseSubAgent 基类 + GeneralSubAgent + 注册表
- builder.py   spec -> CompiledStateGraph（Path A 声明式）
- runner.py    WorkflowRunner：invoke / resume / 中断检测 / LangGraphLoop 发布
- executor.py  WorkflowExecutor：有界 Worker 线程池
- manager.py   WorkflowManager 门面（CRUD + run + resume + 监督）
- tools.py     workflow_* 工具（BaseTool 包装）+ create_workflow_tools
"""

_workflow_manager = None


def get_workflow_manager():
    """获取全局 WorkflowManager 单例（延迟加载）。ENABLE_WORKFLOW=false 或初始化失败返回 None。"""
    global _workflow_manager
    if _workflow_manager is not None:
        return _workflow_manager
    try:
        from config import get_global_config
        cfg = get_global_config()
        if not cfg.ENABLE_WORKFLOW:
            return None
        from agent.workflow.manager import WorkflowManager
        _workflow_manager = WorkflowManager()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("WorkflowManager 初始化失败，降级为 None")
        _workflow_manager = None
    return _workflow_manager
