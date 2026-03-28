"""
Tool package — importing each module causes the BaseTool subclasses
to self-register via __init_subclass__.
"""
from app.tools.base import BaseTool, ToolRegistry
from app.tools.filesystem import FileSystemTool
from app.tools.web_search import WebSearchTool
from app.tools.hyperbrowser import HyperbrowserTool
from app.tools.code_executor import CodeExecutorTool
from app.tools.json_generator import JsonGeneratorTool

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "FileSystemTool",
    "WebSearchTool",
    "HyperbrowserTool",
    "CodeExecutorTool",
    "JsonGeneratorTool",
]
