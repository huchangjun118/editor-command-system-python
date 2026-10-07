"""可扩展开发工具的命令与快捷键系统。"""

from .errors import (
    ArgumentError,
    CommandSystemError,
    ContextError,
    ExecutionError,
    KeybindingError,
    Reason,
    RegistrationError,
)
from .context import ContextKeyDef, ContextKeys, WhenClause
from .registry import (
    ArgumentSpec,
    CommandDescriptor,
    CommandRegistry,
    SourceKind,
)
from .keybindings import (
    KeybindingConflict,
    KeybindingResolver,
    KeybindingRule,
    KeyChord,
    KeySequence,
    Layer,
    Platform,
    ResolvedKeybinding,
)
from .execution import (
    CancellationToken,
    ExecutionEngine,
    ExecutionRecord,
    ExecutionResult,
    Scope,
    Status,
)
from .undo import UndoEntry, UndoStack
from .persistence import StateKind, StateStore
from .terminal import CommandInfo, DeveloperTerminal

__all__ = [
    "ArgumentError",
    "ArgumentSpec",
    "CancellationToken",
    "CommandDescriptor",
    "CommandInfo",
    "CommandRegistry",
    "CommandSystemError",
    "ContextError",
    "ContextKeyDef",
    "ContextKeys",
    "DeveloperTerminal",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionRecord",
    "ExecutionResult",
    "KeybindingConflict",
    "KeybindingError",
    "KeybindingResolver",
    "KeybindingRule",
    "KeyChord",
    "KeySequence",
    "Layer",
    "Platform",
    "Reason",
    "RegistrationError",
    "ResolvedKeybinding",
    "Scope",
    "SourceKind",
    "StateKind",
    "StateStore",
    "Status",
    "UndoEntry",
    "UndoStack",
    "WhenClause",
]
