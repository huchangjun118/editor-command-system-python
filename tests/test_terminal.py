import threading

from command_system import (
    CommandDescriptor,
    CommandRegistry,
    ContextKeys,
    DeveloperTerminal,
    ExecutionEngine,
    Reason,
    Scope,
    SourceKind,
    UndoStack,
)
from command_system.execution import Status


def setup():
    registry = CommandRegistry()
    context = ContextKeys()
    context.define("editorOpen", False)
    engine = ExecutionEngine(registry, context, undo_stack=UndoStack())
    terminal = DeveloperTerminal(engine)

    def add(cid, **kw):
        registry.register_builtin(CommandDescriptor(
            id=cid, title=kw.pop("title", cid), handler=lambda **a: "ok",
            source=SourceKind.BUILTIN, **kw))

    add("file.save", title="File: Save", enablement="editorOpen")
    add("file.open", title="File: Open")
    add("admin.wipe", title="Admin: Wipe", permission="admin")
    return context, engine, terminal


def test_search_finds_by_id_and_title():
    _, _, term = setup()
    hits = term.search("save")
    assert [h.id for h in hits] == ["file.save"]
    assert [h.id for h in term.search("file: o")] == ["file.open"]
    assert len(term.search()) == 3  # 空查询列出全部


def test_search_reports_disabled_reasons():
    _, _, term = setup()
    info = term.search("save")[0]
    assert info.enabled is False
    assert any("enablement" in r for r in info.reasons)


def test_explain_restricted_command():
    _, _, term = setup()
    reasons = term.explain("admin.wipe")
    assert any("admin" in r for r in reasons)


def test_run_uses_terminal_scope_and_denies_permission():
    _, engine, term = setup()
    r = term.run("admin.wipe")
    assert r.status is Status.DENIED and r.reason is Reason.PERMISSION_DENIED
    assert r.record.scope is Scope.TERMINAL
    assert term.run("admin.wipe", permissions=frozenset({"admin"})).ok


def test_concurrent_terminals_consistent_results():
    _, engine, term = setup()
    terminals = [DeveloperTerminal(engine) for _ in range(8)]
    results, errors = [], []

    def work(t):
        try:
            for _ in range(20):
                results.append(len(t.search()))
                t.run("file.open")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work, args=(t,)) for t in terminals]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    assert set(results) == {3}  # 所有终端看到的命令集一致
    succeeded = [h for h in engine.history() if h.status is Status.SUCCEEDED]
    assert len(succeeded) == 8 * 20
