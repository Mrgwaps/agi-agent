from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(settings.workspace_root)


def _sandbox(task_id: str, relative: str) -> Path:
    """Resolve a path inside the task sandbox, raising on escape."""
    base = WORKSPACE_ROOT / task_id
    base.mkdir(parents=True, exist_ok=True)
    target = (base / relative).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise PermissionError(
            f"Path escape attempt: '{relative}' resolves outside sandbox"
        )
    return target


class FileSystemTool(BaseTool):
    name = "filesystem"
    description = (
        "Read, write, list, and create files/directories. "
        "All operations are sandboxed to the task workspace."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_directory", "read_file", "write_file", "create_directory"],
            },
            "path": {"type": "string", "description": "Relative path inside task workspace"},
            "content": {"type": "string", "description": "Content for write_file action"},
        },
        "required": ["action", "path"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        action = input.get("action", "")
        rel_path = input.get("path", "")

        try:
            target = _sandbox(task_id, rel_path)
        except PermissionError as exc:
            return {"success": False, "result": None, "error": str(exc)}

        try:
            if action == "list_directory":
                return self._list_directory(target, rel_path)
            elif action == "read_file":
                return self._read_file(target, rel_path)
            elif action == "write_file":
                content = input.get("content", "")
                return self._write_file(target, rel_path, content)
            elif action == "create_directory":
                return self._create_directory(target, rel_path)
            else:
                return {
                    "success": False,
                    "result": None,
                    "error": f"Unknown action: {action}",
                }
        except Exception as exc:
            logger.exception("FileSystemTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc)}

    # ── Actions ─────────────────────────────────────────────────────────────

    def _list_directory(self, path: Path, rel: str) -> Dict[str, Any]:
        if not path.exists():
            return {"success": False, "result": None, "error": f"Path does not exist: {rel}"}
        if not path.is_dir():
            return {"success": False, "result": None, "error": f"Not a directory: {rel}"}

        entries: List[Dict[str, Any]] = []
        for item in sorted(path.iterdir()):
            entries.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )
        return {"success": True, "result": entries, "error": None}

    def _read_file(self, path: Path, rel: str) -> Dict[str, Any]:
        if not path.exists():
            return {"success": False, "result": None, "error": f"File not found: {rel}"}
        if not path.is_file():
            return {"success": False, "result": None, "error": f"Not a file: {rel}"}

        size = path.stat().st_size
        if size > 2 * 1024 * 1024:  # 2 MB guard
            return {
                "success": False,
                "result": None,
                "error": f"File too large ({size} bytes). Max 2 MB.",
            }

        content = path.read_text(encoding="utf-8", errors="replace")
        return {
            "success": True,
            "result": {"path": rel, "content": content, "size": size},
            "error": None,
        }

    def _write_file(self, path: Path, rel: str, content: str) -> Dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "result": {
                "path": rel,
                "bytes_written": len(content.encode("utf-8")),
            },
            "error": None,
        }

    def _create_directory(self, path: Path, rel: str) -> Dict[str, Any]:
        path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "result": {"path": rel, "created": True}, "error": None}
