from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from convertcom_sdk.enums import LogMethod


class FileLogger:
    def __init__(self, file_path: str, append_method: str = "append") -> None:
        self._file_path = Path(file_path)
        self._append_method = append_method

    def _write(self, method: str, *args: Any) -> None:
        prefix = f"{datetime.now(timezone.utc).isoformat()} [{method.upper()}]"
        output = f"{prefix} " + f"\n{prefix} ".join(json.dumps(arg) for arg in args) + "\n"
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as handle:
                handle.write(output)
        except Exception as error:
            print(error)

    def log(self, *args: Any) -> None:
        self._write(LogMethod.LOG.value, *args)

    def info(self, *args: Any) -> None:
        self._write(LogMethod.INFO.value, *args)

    def debug(self, *args: Any) -> None:
        self._write(LogMethod.DEBUG.value, *args)

    def warn(self, *args: Any) -> None:
        self._write(LogMethod.WARN.value, *args)

    def error(self, *args: Any) -> None:
        self._write(LogMethod.ERROR.value, *args)
