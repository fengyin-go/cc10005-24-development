"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import copy
from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        # 深拷贝种子：血缘样本的处理段是多层嵌套结构，浅拷贝会让运行期写入
        # 反向改到全局种子数据，重置仓库时拿到的就不是干净初始值了。
        self._tables: dict[str, list[dict[str, Any]]] = copy.deepcopy(SEED_ROWS)

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            # 血缘样本/实验表是血缘模块的内部存储，看板指标走 /api/lineage/stats，
            # 不混进通用业务模块列表，避免出现未翻译的内部表名。
            if name.startswith("lineage_"):
                continue
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
