"""tests 专用 aiosqlite stub。

为什么需要它：
- 在某些受限沙箱环境里，真实 `aiosqlite` 依赖后台线程 + `loop.call_soon_threadsafe` 唤醒事件循环；
  若底层 socket/self-pipe 被限制，可能导致 await 永久卡死。
- 本 stub 使用标准库 `sqlite3` 同线程执行 SQL，并提供与 `aiosqlite` 足够兼容的 async API，
  让测试用例能稳定运行且仍能真实执行 SQL（而不是“空实现”）。

注意：
- 这是 tests-only 代码，不影响生产环境运行。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Sequence

import sqlite3


class Cursor:
    """异步游标 stub。"""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    async def execute(self, sql: str, parameters: Any = None) -> "Cursor":
        self._cursor.execute(sql, parameters or ())
        return self

    async def executemany(self, sql: str, parameters: Any = None) -> "Cursor":
        self._cursor.executemany(sql, parameters or ())
        return self

    async def fetchone(self) -> Optional[Any]:
        """获取单行结果。"""
        return self._cursor.fetchone()

    async def fetchall(self) -> list[Any]:
        """获取所有结果。"""
        return self._cursor.fetchall()

    async def fetchmany(self, size: int = 1) -> list[Any]:
        """获取多行结果。"""
        return self._cursor.fetchmany(size)

    async def close(self) -> None:
        """关闭游标。"""
        try:
            self._cursor.close()
        except Exception:
            # sqlite3 关闭游标可能抛错（例如连接已关闭），忽略即可
            return

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        row = self._cursor.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row
    
    async def __aenter__(self) -> "Cursor":
        """支持 async with 语法。"""
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """退出 async with 块。"""
        await self.close()


class _AwaitableContextManager:
    """同时支持 await 和 async with 的包装器。
    
    用法：
    - cursor = await conn.execute(...)
    - async with conn.execute(...) as cursor:
    """
    
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor
    
    def __await__(self):
        """支持 await 表达式。"""
        async def _return_cursor():
            return self._cursor
        return _return_cursor().__await__()
    
    async def __aenter__(self) -> Cursor:
        """支持 async with 语法。"""
        return self._cursor
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """退出 async with 块。"""
        await self._cursor.close()


class Connection:
    """异步连接 stub。"""

    def __init__(self, database: str, **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs
        self._conn = sqlite3.connect(database, **kwargs)
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    def execute(self, sql: str, parameters: Any = None) -> _AwaitableContextManager:
        """执行 SQL 语句。返回同时支持 await 和 async with 的包装器。"""
        if parameters is None:
            raw_cursor = self._conn.execute(sql)
        else:
            raw_cursor = self._conn.execute(sql, parameters)
        cursor = Cursor(raw_cursor)
        return _AwaitableContextManager(cursor)

    def executemany(self, sql: str, parameters: Any = None) -> _AwaitableContextManager:
        """批量执行 SQL 语句。返回同时支持 await 和 async with 的包装器。"""
        params: Sequence[Any]
        if parameters is None:
            params = ()
        else:
            params = parameters
        raw_cursor = self._conn.executemany(sql, params)
        cursor = Cursor(raw_cursor)
        return _AwaitableContextManager(cursor)

    async def executescript(self, sql_script: str) -> Cursor:
        """执行 SQL 脚本。"""
        raw_cursor = self._conn.executescript(sql_script)
        return Cursor(raw_cursor)

    async def commit(self) -> None:
        """提交事务。"""
        self._conn.commit()

    async def rollback(self) -> None:
        """回滚事务。"""
        self._conn.rollback()

    async def close(self) -> None:
        """关闭连接。"""
        if self._closed:
            return
        self._closed = True
        self._conn.close()

    async def cursor(self) -> Cursor:
        """创建游标。"""
        return Cursor(self._conn.cursor())

    async def __aenter__(self) -> "Connection":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class _ConnectContextManager:
    """同时支持 await 和 async with 的连接包装器。"""
    
    def __init__(self, database: str, **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs
        self._connection: Optional[Connection] = None
    
    def __await__(self):
        """支持 await 表达式。"""
        async def _create_connection():
            self._connection = Connection(self._database, **self._kwargs)
            return self._connection
        return _create_connection().__await__()
    
    async def __aenter__(self) -> Connection:
        """支持 async with 语法。"""
        self._connection = Connection(self._database, **self._kwargs)
        return self._connection
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """退出 async with 块。"""
        if self._connection:
            await self._connection.close()


def connect(database: str, **kwargs: Any) -> _ConnectContextManager:
    """创建异步 SQLite 连接。支持 await 和 async with 两种用法。"""
    return _ConnectContextManager(database, **kwargs)


# 兼容常见用法：db.row_factory = aiosqlite.Row
Row = sqlite3.Row
