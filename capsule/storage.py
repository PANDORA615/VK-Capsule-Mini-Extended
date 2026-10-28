import json
import os
import tempfile
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as exc:
            raise RuntimeError(
                f"Invalid state file: {self.path.name}; restore or move it aside"
            ) from exc

    def write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
