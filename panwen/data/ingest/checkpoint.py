import json, os
from typing import Iterable

class Checkpoint:
    """{domain: set(key)} 的 JSON 持久化,记录已完成的粒度(如某 code/某报告期)。"""
    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, list[str]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self._data = json.load(f)

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)

    def mark(self, domain: str, key: str) -> None:
        self._data.setdefault(domain, [])
        if key not in self._data[domain]:
            self._data[domain].append(key)
            self._save()

    def is_done(self, domain: str, key: str) -> bool:
        return key in self._data.get(domain, [])

    def resume_iter(self, domain: str, items: Iterable[str]) -> list[str]:
        return [x for x in items if not self.is_done(domain, x)]
