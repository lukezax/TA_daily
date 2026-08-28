"""
Data sources subpackage.
Expose adapters and manager for backward-compatible imports.
"""
from .base import DataSourceAdapter
from .tushare_adapter import TushareAdapter
from .akshare_adapter import AKShareAdapter
from .baostock_adapter import BaoStockAdapter
from .zhitu_adapter import ZhituAdapter
from .manager import DataSourceManager

