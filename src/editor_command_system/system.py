"""门面：把命令系统各组件组装起来，并负责持久化联动。"""
from __future__ import annotations

from typing import Any

from .context import ContextStore
from .executor import CommandExecutor, ExecutionHandle, ExecutionRequest, ExecutionResult
from .history import HistoryManager
from .keybindings import (
    BindingLayer,
    KeyBinding,
    KeybindingRegistry,
    Platform,
)
from .permissions import PermissionManager
from .persistence import PersistenceStore
from .registry import Command, CommandRegistry
from .terminal import DeveloperTerminal


class CommandSystem:
    def __init__(
        self,
        state_path: str | None = None,
        history_limit: int = 100,
    ) -> None:
        self.context = ContextStore()
        self.registry = CommandRegistry(self.context)
        self.permissions = PermissionManager()
        self.history = HistoryManager(limit=history_limit)
        self.keybindings = KeybindingRegistry(self.context)
        self.executor = CommandExecutor(
            self.registry, self.permissions, self.history, self.context
        )
        self.terminal = DeveloperTerminal(
            self.registry, self.executor, self.keybindings
        )
        self._store = PersistenceStore(state_path)
        self._restore_user_bindings()
        self.registry.add_extension_listener(self._on_extension_event)

    def _on_extension_event(self, extension_id: str, event: str) -> None:
        if event == "deactivated":
            self.keybindings.set_source_active(extension_id, False)
        elif event == "activated":
            self.keybindings.set_source_active(extension_id, True)
        elif event == "removed":
            self.keybindings.remove_source(extension_id)

    # -- 持久化 ------------------------------------------------------------
    def _restore_user_bindings(self) -> None:
        for raw in self._store.load_user_bindings():
            self.keybindings.set_user_binding(
                chord=raw["chord"],
                command_id=raw["command_id"],
                platform=Platform(raw.get("platform", "any")),
                when=raw.get("when"),
            )

    def save(self) -> None:
        bindings = [
            {
                "chord": b.chord,
                "command_id": b.command_id,
                "platform": b.platform.value,
                "when": b.when,
            }
            for b in self.keybindings.all_bindings()
            if b.layer == BindingLayer.USER
        ]
        history = [
            {
                "command_id": e.command_id,
                "args": e.args,
                "timestamp": e.timestamp,
            }
            for e in self.history.entries()
        ]
        self._store.save_user_bindings(bindings)
        self._store.save_history(history)

    def restored_history(self) -> list[dict[str, Any]]:
        """从持久化载入的历史元数据（仅供追溯，不参与撤销）。"""
        return self._store.load_history()

    # -- 便捷转发 ----------------------------------------------------------
    def register(self, command: Command) -> None:
        self.registry.register(command)

    def set_user_binding(
        self, chord: str, command_id: str, platform: Platform = Platform.ANY
    ) -> None:
        self.keybindings.set_user_binding(chord, command_id, platform)
        self.save()

    def execute(
        self, command_id: str, args: dict[str, Any] | None = None,
        caller_scope: str = "user", timeout: float | None = None,
    ) -> ExecutionResult:
        return self.executor.execute(
            ExecutionRequest(command_id, dict(args or {}), caller_scope, timeout)
        )

    def shutdown(self) -> None:
        self.save()
        self.executor.shutdown()
