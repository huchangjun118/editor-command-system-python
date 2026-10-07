import pytest

from command_system import ContextError, ContextKeys, Reason, WhenClause


@pytest.fixture
def keys():
    k = ContextKeys()
    k.define("editorOpen", True)
    k.define("mode", "normal")
    k.define("count", 0)
    return k


def test_undefined_key_rejected_on_set_and_get():
    k = ContextKeys()
    with pytest.raises(ContextError) as e1:
        k.set("nope", 1)
    with pytest.raises(ContextError) as e2:
        k.get("nope")
    assert e1.value.reason is Reason.UNDEFINED_CONTEXT_KEY
    assert e2.value.reason is Reason.UNDEFINED_CONTEXT_KEY


def test_default_value_used_until_set(keys):
    assert keys.get("editorOpen") is True
    keys.set("editorOpen", False)
    assert keys.get("editorOpen") is False


def test_simple_expressions(keys):
    assert WhenClause.parse("editorOpen").evaluate(keys) is True
    assert WhenClause.parse("!editorOpen").evaluate(keys) is False
    assert WhenClause.parse("mode == 'normal'").evaluate(keys) is True
    assert WhenClause.parse("mode != 'normal'").evaluate(keys) is False
    assert WhenClause.parse("count == 0").evaluate(keys) is True


def test_compound_expressions(keys):
    expr = "editorOpen && mode == 'normal' || count != 0"
    assert WhenClause.parse(expr).evaluate(keys) is True
    keys.set("editorOpen", False)
    assert WhenClause.parse(expr).evaluate(keys) is False
    keys.set("count", 3)
    assert WhenClause.parse(expr).evaluate(keys) is True


def test_undefined_key_in_expression_not_silently_passed(keys):
    clause = WhenClause.parse("ghostKey && editorOpen")
    with pytest.raises(ContextError) as exc:
        clause.evaluate(keys)
    assert exc.value.reason is Reason.UNDEFINED_CONTEXT_KEY


def test_evaluation_is_deterministic(keys):
    clause = WhenClause.parse("editorOpen && mode == 'normal'")
    results = {clause.evaluate(keys) for _ in range(50)}
    assert results == {True}


def test_invalid_expression_rejected():
    for bad in ["", "   ", "a &&", "== 1", "(a", "a b", "a == "]:
        with pytest.raises(ContextError) as exc:
            WhenClause.parse(bad)
        assert exc.value.reason is Reason.INVALID_WHEN_EXPRESSION


def test_referenced_keys():
    clause = WhenClause.parse("a && !b || c == 'x'")
    assert clause.referenced_keys() == {"a", "b", "c"}
