"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import site as router_site
from app.routers import template as router_template
from app.routers import proxy as router_proxy
from app.routers import spider as router_spider
from app.routers import schedule as router_schedule
from app.routers import antibot as router_antibot
from app.routers import ratelimit as router_ratelimit
from app.routers import retry as router_retry
from app.routers import extractor as router_extractor
from app.routers import pipeline as router_pipeline
from app.routers import validator as router_validator
from app.routers import storage as router_storage
from app.routers import monitor as router_monitor
from app.routers import cleanse as router_cleanse
from app.routers import delta as router_delta
from app.routers import export as router_export
from app.routers import rpaflow as router_rpaflow
from app.routers import auth as router_auth
from app.routers import lineage as router_lineage

ROUTERS = [router_site, router_template, router_proxy, router_spider, router_schedule, router_antibot, router_ratelimit, router_retry, router_extractor, router_pipeline, router_validator, router_storage, router_monitor, router_cleanse, router_delta, router_export, router_rpaflow, router_auth, router_lineage]
