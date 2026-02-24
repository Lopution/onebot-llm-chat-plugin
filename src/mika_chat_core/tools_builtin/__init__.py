"""内建工具注册（模块导入即触发 @tool 装饰器注册）。"""

from ._history import handle_search_group_history  # noqa: F401
from ._web_search import handle_web_search  # noqa: F401
from ._fetch_images import handle_fetch_history_images  # noqa: F401
from ._knowledge import handle_search_knowledge, handle_ingest_knowledge  # noqa: F401
