"""面向可扩展开发工具的命令与快捷键系统。"""
from __future__ import annotations

from .context import ContextKey, ContextSnapshot, ContextStore
from .errors import (
    CommandAlreadyExistsError,
    CommandCancelledError,
    CommandDisabledError,
    CommandExecutionError,
    CommandNotFoundError,
    CommandRecursionError,
    CommandSystemError,
    ContextEvaluationError,
    InvalidKeybindingError,
    InvalidParameterError,
    KeybindingConflictError,
    PermissionDeniedError,
    UndefinedContextKeyError,
)
from .executor import (
    CancellationToken,
    CommandExecutor,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from .history import HistoryEntry, HistoryManager
from .keybindings import (
    BindingLayer,
    KeyBinding,
    KeybindingRegistry,
    Platform,
    ResolvedBinding,
    normalize_chord,
)
from .permissions import AuditRecord, PermissionManager
from .persistence import PersistenceStore
from .registry import Command, CommandParameter, CommandRegistry
from .system import CommandSystem
from .terminal import CommandExplanation, DeveloperTerminal

__version__ = "0.1.0"

__all__ = [
    "CommandSystem", "Command", "CommandParameter", "CommandRegistry",
    "ContextStore", "ContextKey", "ContextSnapshot",
    "KeybindingRegistry", "KeyBinding", "ResolvedBinding",
    "BindingLayer", "Platform", "normalize_chord",
    "CommandExecutor", "ExecutionRequest", "ExecutionResult",
    "ExecutionHandle", "CancellationToken",
    "PermissionManager", "AuditRecord",
    "HistoryManager", "HistoryEntry",
    "PersistenceStore", "DeveloperTerminal", "CommandExplanation",
    "CommandSystemError", "CommandAlreadyExistsError", "CommandNotFoundError",
    "UndefinedContextKeyError", "ContextEvaluationError",
    "KeybindingConflictError", "InvalidKeybindingError",
    "InvalidParameterError", "CommandExecutionError",
    "CommandRecursionError", "CommandDisabledError",
    "PermissionDeniedError", "CommandCancelledError",
]
