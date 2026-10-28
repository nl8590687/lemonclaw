"""主 Agent 与 Workflow 共用的单库 checkpoint 连接。"""

import weakref

from langgraph.checkpoint.sqlite import SqliteSaver

from dao.db import get_connection


class PersistentSaver(SqliteSaver):
    """复用 DAO 的连接策略；显式关闭或对象回收时释放连接。"""

    def __init__(self):
        connection = get_connection()
        conn = connection.__enter__()
        try:
            super().__init__(conn)
            self.setup()
        except BaseException:
            connection.__exit__(None, None, None)
            raise
        self._close = weakref.finalize(self, connection.__exit__, None, None, None)

    def close(self):
        self._close()
