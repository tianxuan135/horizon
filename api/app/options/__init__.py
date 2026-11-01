"""期权策略计算层（API_CONTRACT §6）。

合规红线（贯穿本包）：
- **只做期权策略盈亏/到期损益计算**，不接任何券商、不生成订单、不提供下单能力；
- 不出现"保证收益/稳赚"类表述，所有输出都是模型推演；
- 期权链没有公开可用数据源时，链上的买卖价由 Black-Scholes 模型 + 已实现波动率
  推演，响应 ``source`` 恒为 ``model:*``，**绝不伪装成真实报价**。
"""

from . import payoff, pricing, strategy_backtest  # noqa: F401