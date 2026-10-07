import pytest

from command_system import (
    CommandDescriptor,
    CommandRegistry,
    Reason,
    RegistrationError,
    SourceKind,
)


def builtin(cid, **kw):
    return CommandDescriptor(id=cid, title=cid, handler=lambda: None,
                             source=SourceKind.BUILTIN, **kw)


def ext(cid, ext_id="ext.a", **kw):
    return CommandDescriptor(id=cid, title=cid, handler=lambda: None,
                             source=SourceKind.EXTENSION, extension_id=ext_id, **kw)


def test_builtin_and_extension_share_registry():
    reg = CommandRegistry()
    reg.register_builtin(builtin("app.save"))
    reg.register_extension_commands("ext.a", [ext("ext.a.fmt")])
    assert reg.has("app.save") and reg.has("ext.a.fmt")
    assert {d.id for d in reg.all()} == {"app.save", "ext.a.fmt"}


def test_duplicate_id_rejected_with_reason():
    reg = CommandRegistry()
    reg.register_builtin(builtin("app.save"))
    with pytest.raises(RegistrationError) as exc:
        reg.register_extension_commands("ext.a", [ext("app.save")])
    assert exc.value.reason is Reason.DUPLICATE_COMMAND_ID
    assert exc.value.detail["existing_source"] == "builtin"
    assert exc.value.detail["new_extension"] == "ext.a"


def test_duplicate_within_batch_rejected_atomically():
    reg = CommandRegistry()
    with pytest.raises(RegistrationError) as exc:
        reg.register_extension_commands("ext.a", [ext("x"), ext("x")])
    assert exc.value.reason is Reason.DUPLICATE_COMMAND_ID
    assert not reg.has("x")  # 整批不生效


def test_conflicting_batch_leaves_registry_untouched():
    reg = CommandRegistry()
    reg.register_builtin(builtin("app.save"))
    with pytest.raises(RegistrationError):
        reg.register_extension_commands("ext.a", [ext("ok.cmd"), ext("app.save")])
    assert not reg.has("ok.cmd")  # 原子性：ok.cmd 也不应注册
    assert reg.has("app.save")


def test_unregister_extension_removes_only_its_commands():
    reg = CommandRegistry()
    reg.register_builtin(builtin("app.save"))
    reg.register_extension_commands("ext.a", [ext("a.one"), ext("a.two")])
    reg.register_extension_commands("ext.b", [ext("b.one", ext_id="ext.b")])
    reg.unregister_extension("ext.a")
    assert not reg.has("a.one") and not reg.has("a.two")
    assert reg.has("app.save") and reg.has("b.one")


def test_unregister_unknown_extension():
    reg = CommandRegistry()
    with pytest.raises(RegistrationError) as exc:
        reg.unregister_extension("ghost")
    assert exc.value.reason is Reason.UNKNOWN_EXTENSION


def test_get_missing_command():
    reg = CommandRegistry()
    with pytest.raises(RegistrationError) as exc:
        reg.get("missing")
    assert exc.value.reason is Reason.COMMAND_NOT_FOUND


def test_re_register_after_unregister():
    reg = CommandRegistry()
    reg.register_extension_commands("ext.a", [ext("a.one")])
    reg.unregister_extension("ext.a")
    reg.register_extension_commands("ext.a", [ext("a.one")])
    assert reg.has("a.one")


def test_descriptor_source_validation():
    with pytest.raises(RegistrationError) as exc:
        CommandDescriptor(id="x", title="x", handler=lambda: None,
                          source=SourceKind.EXTENSION)
    assert exc.value.reason is Reason.UNKNOWN_EXTENSION
