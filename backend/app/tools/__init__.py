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
from app.tools.content_writer import ContentWriterTool
from app.tools.web_researcher import WebResearcherTool
from app.tools.image_generator import ImageGeneratorTool
from app.tools.enhanced_search import EnhancedSearchTool
from app.tools.location_tool import LocationTool
from app.tools.hf_inference import HFInferenceTool

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "FileSystemTool",
    "WebSearchTool",
    "HyperbrowserTool",
    "CodeExecutorTool",
    "JsonGeneratorTool",
    "ContentWriterTool",
    "WebResearcherTool",
    "ImageGeneratorTool",
    "EnhancedSearchTool",
    "LocationTool",
    "HFInferenceTool",
]
