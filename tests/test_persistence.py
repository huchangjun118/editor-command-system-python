from command_system import StateKind, StateStore


def test_roundtrip_and_kind_distinction(tmp_path):
    store = StateStore(tmp_path / "state")
    assert store.load(StateKind.USER_KEYBINDINGS) is None  # 从未保存
    store.save(StateKind.USER_KEYBINDINGS, {"rules": [{"key": "ctrl+s"}]})
    store.save(StateKind.HISTORY, {"entries": []})
    assert store.load(StateKind.USER_KEYBINDINGS) == {"rules": [{"key": "ctrl+s"}]}
    assert store.load(StateKind.HISTORY) == {"entries": []}  # 空状态与 None 可区分


def test_restart_keeps_state(tmp_path):
    d = tmp_path / "state"
    StateStore(d).save(StateKind.HISTORY, {"entries": [1, 2, 3]})
    # 模拟重启：新建实例读取同一目录
    assert StateStore(d).load(StateKind.HISTORY) == {"entries": [1, 2, 3]}


def test_no_temp_files_left(tmp_path):
    store = StateStore(tmp_path)
    store.save(StateKind.HISTORY, {"a": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["history.json"]
