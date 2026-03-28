from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Optional, Type

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for all agent tools."""

    # Subclasses must set these class-level attributes
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires_approval: ClassVar[bool] = False
    schema: ClassVar[Dict[str, Any]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            ToolRegistry.register(cls)

    @abstractmethod
    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        """
        Execute the tool with the given input dict.

        Returns a dict with at minimum:
            - success: bool
            - result: Any  (the main output)
            - error: Optional[str]
        """
        ...

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "requires_approval": self.requires_approval,
            "schema": self.schema,
        }


class ToolRegistry:
    """Central registry for all available tools."""

    _registry: Dict[str, Type[BaseTool]] = {}
    _instances: Dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool_cls: Type[BaseTool]) -> None:
        if tool_cls.name:
            cls._registry[tool_cls.name] = tool_cls
            logger.debug("Registered tool: %s", tool_cls.name)

    @classmethod
    def get(cls, name: str) -> Optional[BaseTool]:
        """Return a singleton instance of the named tool."""
        if name not in cls._instances:
            tool_cls = cls._registry.get(name)
            if tool_cls is None:
                return None
            cls._instances[name] = tool_cls()
        return cls._instances[name]

    @classmethod
    def list_tools(cls) -> Dict[str, Dict[str, Any]]:
        return {
            name: cls.get(name).to_dict()  # type: ignore[union-attr]
            for name in cls._registry
        }

    @classmethod
    def all_names(cls) -> list[str]:
        return list(cls._registry.keys())
