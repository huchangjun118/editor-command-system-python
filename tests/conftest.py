from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from editor_command_system.context import ContextKey, ContextStore
from editor_command_system.executor import CommandExecutor
from editor_command_system.history import HistoryManager
from editor_command_system.keybindings import KeybindingRegistry
from editor_command_system.permissions import PermissionManager
from editor_command_system.registry import CommandRegistry


@pytest.fixture
def context():
    store = ContextStore()
    store.define_key(ContextKey("editorFocused", False))
    store.define_key(ContextKey("mode", "normal"))
    store.define_key(ContextKey("dirty", False))
    return store


@pytest.fixture
def registry(context):
    return CommandRegistry(context)


@pytest.fixture
def permissions():
    return PermissionManager()


@pytest.fixture
def history():
    return HistoryManager()


@pytest.fixture
def executor(registry, permissions, history, context):
    ex = CommandExecutor(registry, permissions, history, context)
    yield ex
    ex.shutdown()


@pytest.fixture
def keybindings(context):
    return KeybindingRegistry(context)
