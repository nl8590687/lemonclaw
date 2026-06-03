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
睡眠等待工具，用于同步等待指定秒数
"""

import time
from langchain_core.tools import tool


@tool
def sleep(interval: int) -> str:
    """
    通过睡眠指定秒数以同步等待某个状态的变化，等待时间1-3600秒之间

    Args:
        interval (int): 睡眠的秒数，例如 30

    Returns:
        str: 工具执行后的结果

    Example:
        sleep(interval=30) -> "睡眠完成：计划等待 30 秒，实际等待 30 秒"
    """
    if not 1 <= interval <= 3600:
        return f"错误：interval 必须在 1-3600 之间，当前值: {interval}"

    start = time.time()
    time.sleep(interval)
    actual = time.time() - start

    return f"睡眠完成：计划等待 {interval} 秒，实际等待 {actual:.2f} 秒"


def create_sleep_tool():
    """
    创建睡眠工具
    """
    return sleep
