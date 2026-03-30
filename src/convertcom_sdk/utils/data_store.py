from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DataStore:
    def __init__(self, file_path: str) -> None:
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._file_path.exists():
            self._file_path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get(self, key: str) -> Any:
        return self._read().get(key)

    def set(self, key: str, value: Any) -> None:
        data = self._read()
        data[key] = value
        self._file_path.write_text(json.dumps(data), encoding="utf-8")

    def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._file_path.write_text(json.dumps(data), encoding="utf-8")
