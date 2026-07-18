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
执行层：WorkflowExecutor

有界 Worker 线程池，分段执行工作流（主循环不阻塞，§4.9）。
"""

import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """有界 Worker 线程池：工作流分段在后台执行，主循环不阻塞。"""

    def __init__(self, pool_size: int = 4):
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, pool_size),
            thread_name_prefix="wf-worker",
        )

    def submit(self, fn, *args, **kwargs):
        """提交一个工作流分段任务（非阻塞）。"""
        self._pool.submit(fn, *args, **kwargs)

    def shutdown(self):
        """关闭线程池（不等任务完成）。"""
        self._pool.shutdown(wait=False)
