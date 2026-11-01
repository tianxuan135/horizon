"""回测与因子研究引擎（API_CONTRACT §5）。

设计原则：
- 横截面等权组合，月度调仓，全部用真实收盘价计算，不用未来数据；
- 交易成本按换手率计提（默认 5bp，可在请求里覆盖）；
- 指标口径全部写在 metrics.py 的 docstring 里，避免"看起来对"的黑箱。
"""

from . import engine, metrics, strategies  # noqa: F401