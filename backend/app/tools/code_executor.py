from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Patterns that will be blocked/warned about
DANGEROUS_PATTERNS: List[str] = [
    "os.system",
    "subprocess",
    "__import__('os')",
    "__import__('subprocess')",
    "eval(",
    "exec(",
    "open('/etc",
    "open('/proc",
    "open('/sys",
    "shutil.rmtree",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "socket.socket",
    "urllib.request",
    "http.client",
]

EXECUTION_TIMEOUT = 30  # seconds


class CodeExecutorTool(BaseTool):
    name = "code_executor"
    description = (
        "Execute Python code in a sandboxed subprocess. "
        "Captures stdout, stderr, and return code. "
        "Dangerous operations (subprocess, os.system, etc.) are blocked."
    )
    requires_approval = True
    schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (max 30)",
                "default": 30,
            },
        },
        "required": ["code"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        code: str = input.get("code", "").strip()
        timeout: int = min(int(input.get("timeout", EXECUTION_TIMEOUT)), EXECUTION_TIMEOUT)

        if not code:
            return {"success": False, "result": None, "error": "code is required"}

        # Safety check
        warnings: List[str] = []
        sanitized_code, warnings = self._sanitize(code)

        try:
            result = await self._run_code(sanitized_code, task_id, timeout)
            result["warnings"] = warnings
            return result
        except asyncio.TimeoutError:
            return {
                "success": False,
                "result": None,
                "error": f"Code execution timed out after {timeout}s",
                "warnings": warnings,
            }
        except Exception as exc:
            logger.exception("CodeExecutorTool error: %s", exc)
            return {"success": False, "result": None, "error": str(exc), "warnings": warnings}

    # ── Sanitization ─────────────────────────────────────────────────────────

    def _sanitize(self, code: str) -> tuple[str, List[str]]:
        warnings: List[str] = []
        lines = code.splitlines()
        clean_lines: List[str] = []

        for line in lines:
            blocked = False
            for pattern in DANGEROUS_PATTERNS:
                if pattern in line:
                    clean_lines.append(
                        f"# [BLOCKED] {line}  # pattern '{pattern}' not allowed"
                    )
                    warnings.append(
                        f"Blocked dangerous pattern '{pattern}' in: {line.strip()[:80]}"
                    )
                    blocked = True
                    break
            if not blocked:
                clean_lines.append(line)

        return "\n".join(clean_lines), warnings

    # ── Execution ─────────────────────────────────────────────────────────────

    async def _run_code(
        self, code: str, task_id: str, timeout: int
    ) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"agi_exec_{task_id}_") as tmpdir:
            script_path = Path(tmpdir) / "script.py"
            script_path.write_text(code, encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=tmpdir,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "HOME": tmpdir,
                    "TMPDIR": tmpdir,
                },
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            returncode = proc.returncode or 0

            # Truncate long output
            if len(stdout) > 10_000:
                stdout = stdout[:10_000] + "\n...[stdout truncated]"
            if len(stderr) > 4_000:
                stderr = stderr[:4_000] + "\n...[stderr truncated]"

            success = returncode == 0
            return {
                "success": success,
                "result": {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                },
                "error": stderr if not success else None,
            }
