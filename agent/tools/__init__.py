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
工具模块
"""
from typing import Any

from agent.tools.bocha_search import BochaSearchTool, create_bocha_tool
from agent.tools.time_tool import create_time_tool
from agent.tools.http_request import http_request, create_http_request_tool
from agent.tools.web_fetch import create_web_fetch_tool
from agent.tools.file_list_query import FileListQueryTool, create_file_list_query_tool
from agent.tools.file_editor import ReadFileTool, WriteFileTool, create_read_file_tool, create_write_file_tool
from agent.tools.file_editor_incremental import EditFileTool, create_edit_file_tool
from agent.tools.git_tool import GitTool, create_git_tool
from agent.tools.email_tool import EmailTool, create_email_tool
from agent.tools.bash_tool import BashTool, create_bash_tool
from agent.tools.sleep_tool import create_sleep_tool
from agent.tools.glob_tool import GlobTool, create_glob_tool
from agent.tools.grep_tool import GrepTool, create_grep_tool
from agent.tools.cron_tool import create_cron_tools
from channels.device.crontab import get_cron_manager
from config import get_global_config

__all__ = [
    "create_bocha_tool",
    "create_time_tool",
    "create_http_request_tool",
    "create_web_fetch_tool",
    "create_file_list_query_tool",
    "create_read_file_tool",
    "create_write_file_tool",
    "create_edit_file_tool",
    "create_git_tool",
    "create_email_tool",
    "create_bash_tool",
    "create_sleep_tool",
    "create_glob_tool",
    "create_grep_tool",
    "create_cron_tools",
]


def create_tool_list() -> dict[str, Any]:
    """
    创建所有工具
    """
    config = get_global_config()
    file_safe_dirs = config.FILE_SAFE_DIRS.split(";")
    tools = [
        create_time_tool(),
        create_http_request_tool(),
        create_web_fetch_tool(),
        create_git_tool(),
        create_sleep_tool(),
        create_file_list_query_tool(file_safe_dirs),
        create_read_file_tool(file_safe_dirs),
        create_write_file_tool(file_safe_dirs),
        create_edit_file_tool(file_safe_dirs),
        create_grep_tool(file_safe_dirs),
        create_glob_tool(file_safe_dirs),
    ]

    if config.BOCHA_API_KEY:
        tools.append(create_bocha_tool(config.BOCHA_API_URL, config.BOCHA_API_KEY))

    if config.EMAIL_SMTP_SERVER and config.EMAIL_SMTP_USERNAME and config.EMAIL_SMTP_PASSWORD:
        tools.append(create_email_tool(config.EMAIL_SMTP_SERVER, config.EMAIL_SMTP_ENCRYPTION, config.EMAIL_SMTP_PORT,
                                       config.EMAIL_SMTP_USERNAME, config.EMAIL_SMTP_PASSWORD, config.EMAIL_FROM_NAME))
    if config.ENABLE_BASH_TOOL:
        tools.append(create_bash_tool())

    # Cron 定时任务管理工具（与调度器共享同一个 manager 单例，
    # 新建/修改/删除的任务会实时同步到正在运行的调度器）
    tools.extend(create_cron_tools(get_cron_manager()))

    return tools
