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
Cron 定时任务管理工具集

提供给 AI Agent 使用的工具，用于动态管理定时任务：
- list_cron_tasks - 列出所有定时任务
- create_cron_task - 创建新定时任务
- update_cron_task - 更新已有任务
- delete_cron_task - 删除任务
- enable_cron_task - 启用任务
- disable_cron_task - 禁用任务
- get_cron_task - 获取单个任务详情
"""
from typing import Any, Dict, Optional, Type
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

# 导入 cron 模块
from channels.device.crontab import CronTaskManager, CronTask


# ==================== 工具输入模型 ====================

class ListCronTasksInput(BaseModel):
    """列出 Cron 任务工具的输入"""
    include_disabled: bool = Field(default=False, description="是否包含已禁用的任务，默认False")


class CreateCronTaskInput(BaseModel):
    """创建 Cron 任务工具的输入"""
    prompt: str = Field(..., description="任务触发时发送给 AI Agent 的提示词")
    cron_expression: str = Field(..., description="Cron 表达式，格式为 '分 时 日 月 周'，例如 '* * * * *' 表示每分钟执行")
    enabled: bool = Field(default=True, description="是否立即启用，默认True")


class UpdateCronTaskInput(BaseModel):
    """更新 Cron 任务工具的输入"""
    task_id: str = Field(..., description="要更新的任务ID")
    prompt: Optional[str] = Field(default=None, description="新的提示词，不修改则留空")
    cron_expression: Optional[str] = Field(default=None, description="新的Cron表达式，不修改则留空")
    enabled: Optional[bool] = Field(default=None, description="是否启用，不修改则留空")


class DeleteCronTaskInput(BaseModel):
    """删除 Cron 任务工具的输入"""
    task_id: str = Field(..., description="要删除的任务ID")


class EnableCronTaskInput(BaseModel):
    """启用 Cron 任务工具的输入"""
    task_id: str = Field(..., description="要启用的任务ID")


class DisableCronTaskInput(BaseModel):
    """禁用 Cron 任务工具的输入"""
    task_id: str = Field(..., description="要禁用的任务ID")


class GetCronTaskInput(BaseModel):
    """获取 Cron 任务详情工具的输入"""
    task_id: str = Field(..., description="要查看的任务ID")


# ==================== 工具实现 ====================

class ListCronTasksTool(BaseTool):
    """列出所有 Cron 定时任务的工具"""

    name: str = "list_cron_tasks"
    description: str = """列出所有已注册的 Cron 定时任务，返回任务ID、状态、执行计划、下次执行时间等信息。
使用场景：
- 查看当前有哪些定时任务
- 检查任务是否启用
- 查看任务的执行计划"""
    args_schema: Type[BaseModel] = ListCronTasksInput

    # 使用 PrivateAttr 来保存非 Pydantic 字段
    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, include_disabled: bool = False, *args, **kwargs) -> str:
        """执行列出任务"""
        try:
            tasks = self._manager.list_tasks(include_disabled=include_disabled)

            if not tasks:
                return "当前没有定时任务"

            result = ["= Cron 定时任务列表 ="]
            for task in tasks:
                status = "✅ 已启用" if task.enabled else "❌ 已禁用"
                last_run = task.last_run_at.strftime("%Y-%m-%d %H:%M") if task.last_run_at else "从未执行"
                result.append(f"""
任务ID: {task.task_id}
状态: {status}
执行计划: {task.cron_expression}
最后执行: {last_run}
提示词: {task.prompt[:100]}{"..." if len(task.prompt) > 100 else ""}
""")
            return "\n".join(result)
        except Exception as e:
            return f"列出任务失败: {str(e)}"


class CreateCronTaskTool(BaseTool):
    """创建 Cron 定时任务的工具"""

    name: str = "create_cron_task"
    description: str = """创建一个新的 Cron 定时任务。任务触发时，会自动将指定的提示词发送给 AI Agent 执行。

Cron 表达式格式: 分 时 日 月 周
- * * * * * 每分钟执行
- 0 * * * * 每小时执行
- 0 9 * * * 每天9:00执行
- 0 9 * * 1-5 工作日9:00执行
- 0 9,18 * * * 每天9:00和18:00执行
- */30 * * * * 每30分钟执行

快捷表达式：
- @hourly 每小时
- @daily 每天
- @weekly 每周
- @monthly 每月

使用场景示例：
- 创建一个每天早上9点提醒的任务
- 创建一个每小时检查某个网站更新的任务
- 创建一个定时执行工作总结的任务"""
    args_schema: Type[BaseModel] = CreateCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, prompt: str, cron_expression: str, enabled: bool = True, *args, **kwargs) -> str:
        """执行创建任务"""
        try:
            task = self._manager.create_task(
                prompt=prompt,
                prompt_original=prompt,
                cron_expression=cron_expression,
                enabled=enabled
            )
            if task:
                return f"✅ 任务创建成功！任务ID: {task.task_id}, 执行计划: {task.cron_expression}"
            else:
                return "❌ 任务创建失败"
        except Exception as e:
            return f"❌ 创建任务失败: {str(e)}"


class UpdateCronTaskTool(BaseTool):
    """更新 Cron 定时任务的工具"""

    name: str = "update_cron_task"
    description: str = """更新已有的 Cron 定时任务。可以修改提示词、执行计划、启用/禁用状态。"""
    args_schema: Type[BaseModel] = UpdateCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, task_id: str, prompt: Optional[str] = None, cron_expression: Optional[str] = None, enabled: Optional[bool] = None, *args, **kwargs) -> str:
        """执行更新任务"""
        try:
            task = self._manager.update_task(
                task_id=task_id,
                prompt=prompt,
                cron_expression=cron_expression,
                enabled=enabled
            )
            if task:
                return f"✅ 任务更新成功！任务ID: {task_id}"
            else:
                return f"❌ 任务更新失败，可能任务不存在: {task_id}"
        except Exception as e:
            return f"❌ 更新任务失败: {str(e)}"


class DeleteCronTaskTool(BaseTool):
    """删除 Cron 定时任务的工具"""

    name: str = "delete_cron_task"
    description: str = """删除指定的 Cron 定时任务。删除后任务将不再执行。"""
    args_schema: Type[BaseModel] = DeleteCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, task_id: str, *args, **kwargs) -> str:
        """执行删除任务"""
        try:
            success = self._manager.delete_task(task_id)
            if success:
                return f"✅ 任务删除成功！任务ID: {task_id}"
            else:
                return f"❌ 任务删除失败，可能任务不存在: {task_id}"
        except Exception as e:
            return f"❌ 删除任务失败: {str(e)}"


class EnableCronTaskTool(BaseTool):
    """启用 Cron 定时任务的工具"""

    name: str = "enable_cron_task"
    description: str = """启用已禁用的 Cron 定时任务，任务将按照执行计划恢复执行。"""
    args_schema: Type[BaseModel] = EnableCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, task_id: str, *args, **kwargs) -> str:
        """执行启用任务"""
        try:
            success = self._manager.enable_task(task_id)
            if success:
                return f"✅ 任务已启用！任务ID: {task_id}"
            else:
                return f"❌ 启用任务失败，可能任务不存在: {task_id}"
        except Exception as e:
            return f"❌ 启用任务失败: {str(e)}"


class DisableCronTaskTool(BaseTool):
    """禁用 Cron 定时任务的工具"""

    name: str = "disable_cron_task"
    description: str = """禁用 Cron 定时任务，任务将停止执行，但保留配置和数据。需要时可以重新启用。"""
    args_schema: Type[BaseModel] = DisableCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, task_id: str, *args, **kwargs) -> str:
        """执行禁用任务"""
        try:
            success = self._manager.disable_task(task_id)
            if success:
                return f"✅ 任务已禁用！任务ID: {task_id}"
            else:
                return f"❌ 禁用任务失败，可能任务不存在: {task_id}"
        except Exception as e:
            return f"❌ 禁用任务失败: {str(e)}"


class GetCronTaskTool(BaseTool):
    """获取 Cron 任务详情的工具"""

    name: str = "get_cron_task"
    description: str = """获取单个 Cron 任务的详细信息，包括完整的提示词、执行历史、最后执行时间等。"""
    args_schema: Type[BaseModel] = GetCronTaskInput

    _manager: CronTaskManager = PrivateAttr()

    def __init__(self, manager: CronTaskManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager = manager

    def _run(self, task_id: str, *args, **kwargs) -> str:
        """执行获取任务详情"""
        try:
            task = self._manager.get_task(task_id)
            if task:
                status = "✅ 已启用" if task.enabled else "❌ 已禁用"
                last_run = task.last_run_at.strftime("%Y-%m-%d %H:%M") if task.last_run_at else "从未执行"
                created_at = task.created_at.strftime("%Y-%m-%d %H:%M")
                updated_at = task.updated_at.strftime("%Y-%m-%d %H:%M")

                return f"""= Cron 任务详情 =
任务ID: {task.task_id}
状态: {status}
执行计划: {task.cron_expression}
创建时间: {created_at}
最后更新: {updated_at}
最后执行: {last_run}

完整提示词:
{task.prompt}
"""
            else:
                return f"❌ 任务不存在: {task_id}"
        except Exception as e:
            return f"❌ 获取任务详情失败: {str(e)}"


# ==================== 工厂函数 ====================

def create_cron_tools(manager: CronTaskManager) -> list:
    """
    创建所有 Cron 相关工具

    Args:
        manager: CronTaskManager 实例

    Returns:
        工具实例列表
    """
    return [
        ListCronTasksTool(manager),
        CreateCronTaskTool(manager),
        UpdateCronTaskTool(manager),
        DeleteCronTaskTool(manager),
        EnableCronTaskTool(manager),
        DisableCronTaskTool(manager),
        GetCronTaskTool(manager),
    ]
