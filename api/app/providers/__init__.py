"""数据源适配层。

设计原则（合规相关）：
1. 只接入合法公开/开源接口，不内置任何针对受保护站点的爬虫；
2. 所有凭据来自环境变量；
3. 任一数据源失败时逐级降级，最终回落到 deterministic synthetic 代理数据，并如实上报来源。
"""

from .base import Bar, SourceStatus, get_bars, get_quote, provider_status, search_symbols  # noqa: F401