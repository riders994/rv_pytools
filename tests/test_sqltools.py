import json
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rv_pytools.sqltools.connections import ConnectionManager
from rv_pytools.sqltools.manager import Manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_conn():
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(
        return_value=conn.cursor.return_value.__enter__.return_value
    )
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


def _cursor(conn):
    return conn.cursor.return_value.__enter__.return_value


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

def test_cm_init():
    cm = ConnectionManager()
    assert cm.connections == {}
    assert cm.last_connector is None
    assert cm._current_connector is None


def test_cm_instances_do_not_share_connections():
    a, b = ConnectionManager(), ConnectionManager()
    a.connections["x"] = MagicMock()
    assert "x" not in b.connections


def test_cm_connect_stores_and_sets_last():
    cm = ConnectionManager()
    mock = MagicMock()
    with patch("rv_pytools.sqltools.connections.psycopg2.connect", return_value=mock):
        conn = cm.connect("db", {"host": "localhost"})
    assert conn is mock
    assert cm.connections["db"] is mock
    assert cm.last_connector is mock


def test_cm_connect_multiple_names():
    cm = ConnectionManager()
    m1, m2 = MagicMock(), MagicMock()
    with patch("rv_pytools.sqltools.connections.psycopg2.connect", side_effect=[m1, m2]):
        cm.connect("a", {})
        cm.connect("b", {})
    assert cm.connections["a"] is m1
    assert cm.connections["b"] is m2
    assert cm.last_connector is m2


def test_cm_set_last_connection():
    cm = ConnectionManager()
    mock = MagicMock()
    cm.set_last_connection(mock)
    assert cm.last_connector is mock


def test_cm_set_connection_by_name():
    cm = ConnectionManager()
    mock = MagicMock()
    cm.connections["db1"] = mock
    result = cm.set_connection("db1")
    assert result is mock
    assert cm._current_connector is mock


def test_cm_set_connection_unknown_falls_back_to_last():
    cm = ConnectionManager()
    mock = MagicMock()
    cm.last_connector = mock
    result = cm.set_connection("nonexistent")
    assert result is mock


def test_cm_set_connection_no_name_uses_last():
    cm = ConnectionManager()
    mock = MagicMock()
    cm.last_connector = mock
    result = cm.set_connection()
    assert result is mock


def test_cm_current_connector_lazily_resolves_last():
    cm = ConnectionManager()
    mock = MagicMock()
    cm.last_connector = mock
    assert cm.current_connector is mock


def test_cm_current_connector_returns_explicit_value():
    cm = ConnectionManager()
    mock = MagicMock()
    cm._current_connector = mock
    assert cm.current_connector is mock


def test_cm_current_connector_falsy_connection_not_replaced():
    cm = ConnectionManager()
    closed_conn = MagicMock()
    closed_conn.__bool__ = MagicMock(return_value=False)
    last_conn = MagicMock()
    cm._current_connector = closed_conn
    cm.last_connector = last_conn
    assert cm.current_connector is closed_conn


def test_cm_set_connection_unknown_does_not_clobber_current():
    cm = ConnectionManager()
    existing = MagicMock()
    cm._current_connector = existing
    cm.set_connection("nonexistent")
    assert cm._current_connector is existing


# ---------------------------------------------------------------------------
# Manager fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr(tmp_path):
    return Manager(
        log_path=tmp_path / "test.log.json",
        sql_dir=tmp_path / "sql",
    )


# ---------------------------------------------------------------------------
# Manager.__init__
# ---------------------------------------------------------------------------

def test_manager_init_creates_dirs(tmp_path):
    m = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    for sub in ("databases", "ddl", "queries"):
        assert (tmp_path / "sql" / sub).is_dir()


def test_manager_init_empty_log_and_queries(mgr):
    assert mgr.log == []
    assert mgr.queries == {}


def test_manager_is_connection_manager(mgr):
    assert isinstance(mgr, ConnectionManager)


# ---------------------------------------------------------------------------
# Manager.connect / set_connection
# ---------------------------------------------------------------------------

def test_manager_connect_delegates_to_super(mgr):
    mock = MagicMock()
    with patch("rv_pytools.sqltools.connections.psycopg2.connect", return_value=mock):
        conn = mgr.connect("mydb", {"host": "localhost"})
    assert conn is mock
    assert mgr.connections["mydb"] is mock
    assert mgr.last_connector is mock


def test_manager_set_connection_by_name(mgr):
    mock = MagicMock()
    mgr.connections["db1"] = mock
    assert mgr.set_connection("db1") is mock


def test_manager_set_connection_no_name_uses_last(mgr):
    mock = MagicMock()
    mgr.last_connector = mock
    assert mgr.set_connection() is mock


# ---------------------------------------------------------------------------
# Manager log methods
# ---------------------------------------------------------------------------

def test_add_log_entry(mgr):
    entry = mgr.add_log_entry("/some/file.sql", "SCANNED")
    assert entry.file_id == 1
    assert entry.file_path == "/some/file.sql"
    assert entry.last_action == "SCANNED"
    assert len(mgr.log) == 1


def test_add_log_entry_increments_id(mgr):
    e1 = mgr.add_log_entry("/a.sql", "SCANNED")
    e2 = mgr.add_log_entry("/b.sql", "SCANNED")
    assert e2.file_id == e1.file_id + 1


def test_update_log_entry(mgr):
    mgr.add_log_entry("/a.sql", "SCANNED")
    fid = mgr.log[0].file_id
    result = mgr.update_log_entry(fid, "RUN")
    assert result is mgr.log[0]
    assert result.last_action == "RUN"


def test_update_log_entry_missing_returns_none(mgr):
    assert mgr.update_log_entry(999, "RUN") is None


def test_save_and_reload_log(tmp_path):
    m = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    m.add_log_entry("/a.sql", "SCANNED")
    m.save_log()
    m2 = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    assert len(m2.log) == 1
    assert m2.log[0].file_path == "/a.sql"
    assert m2.log[0].last_action == "SCANNED"


def test_read_log_resolves_relative_paths(tmp_path):
    import json
    from rv_pytools.classes import ConnectionManagerLogEntry
    from dataclasses import asdict
    log_path = tmp_path / "test.log.json"
    sql_dir = tmp_path / "sql"
    # Write a log entry with a relative path (simulating pre-resolve logs)
    rel_path = "sql/ddl/old.sql"
    entry = ConnectionManagerLogEntry(
        file_id=1, file_path=rel_path,
        date_scanned="2026-01-01T00:00:00", date_last_action="2026-01-01T00:00:00",
        last_action="RUN",
    )
    log_path.write_text(json.dumps([asdict(entry)]))
    m = Manager(log_path=log_path, sql_dir=sql_dir)
    assert m.log[0].file_path == str(Path(rel_path).resolve())


def test_scan_deduplicates_after_path_migration(tmp_path):
    import json
    from rv_pytools.classes import ConnectionManagerLogEntry
    from dataclasses import asdict
    log_path = tmp_path / "test.log.json"
    sql_dir = tmp_path / "sql"
    f = sql_dir / "ddl" / "t.sql"
    # Write a log entry with the relative path form of f
    rel_path = str(f.relative_to(Path.cwd())) if f.is_relative_to(Path.cwd()) else str(f)
    entry = ConnectionManagerLogEntry(
        file_id=1, file_path=str(f),
        date_scanned="2026-01-01T00:00:00", date_last_action="2026-01-01T00:00:00",
        last_action="RUN",
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps([asdict(entry)]))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("SELECT 1;")
    m = Manager(log_path=log_path, sql_dir=sql_dir)
    m.scan("ddl")
    assert len(m.log) == 1


# ---------------------------------------------------------------------------
# Manager query persistence
# ---------------------------------------------------------------------------

def test_save_and_read_queries(mgr):
    mgr.queries["my_query"] = "SELECT 1"
    mgr._save_queries()
    reloaded = mgr._read_queries()
    assert reloaded["my_query"] == "SELECT 1"


def test_queries_persisted_at_init(tmp_path):
    m = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    m.queries["q1"] = "SELECT 1"
    m._save_queries()
    m2 = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    assert m2.queries["q1"] == "SELECT 1"


# ---------------------------------------------------------------------------
# Manager.scan
# ---------------------------------------------------------------------------

def test_scan_discovers_ddl(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    entries = mgr.scan("ddl")
    assert any(e.file_path == str(f) for e in entries)
    assert all(e.last_action == "SCANNED" for e in entries)


def test_scan_discovers_databases_in_subdir(mgr, tmp_path):
    d = tmp_path / "sql" / "databases" / "mydb"
    d.mkdir()
    f = d / "setup.sql"
    f.write_text("CREATE DATABASE mydb;")
    entries = mgr.scan("databases")
    assert any(e.file_path == str(f) for e in entries)


def test_scan_discovers_databases_flat(mgr, tmp_path):
    f = tmp_path / "sql" / "databases" / "mydb.sql"
    f.write_text("CREATE TABLE t (id INT);")
    entries = mgr.scan("databases")
    assert any(e.file_path == str(f) for e in entries)


def test_scan_marks_missing_as_wiped(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    f.unlink()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        mgr.scan("ddl")
    entry = next(e for e in mgr.log if e.file_path == str(f))
    assert entry.last_action == "WIPED"


def test_scan_persists_log(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "t.sql"
    f.write_text("SELECT 1;")
    mgr.scan("ddl")
    assert mgr.log_path.exists()


def test_scan_does_not_overwrite_run_status(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    assert mgr.log[0].last_action == "RUN"
    mgr.scan("queries")
    assert mgr.log[0].last_action == "RUN"


# ---------------------------------------------------------------------------
# Manager.delete_files
# ---------------------------------------------------------------------------

def test_delete_files_removes_file(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    mgr.delete_files("create_table.sql", subdir="ddl")
    assert not f.exists()


def test_delete_files_updates_log(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    mgr.delete_files("create_table.sql", subdir="ddl")
    entry = next(e for e in mgr.log if "create_table.sql" in e.file_path)
    assert entry.last_action == "deleted"


def test_delete_query_removes_from_queries_dict(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.queries["get_users"] = "SELECT * FROM users;"
    mgr._save_queries()
    mgr.delete_files("get_users.sql", subdir="queries")
    assert "get_users" not in mgr.queries


def test_delete_query_persists_removal(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.queries["get_users"] = "SELECT * FROM users;"
    mgr._save_queries()
    mgr.delete_files("get_users.sql", subdir="queries")
    reloaded = mgr._read_queries()
    assert "get_users" not in reloaded


def test_delete_non_query_does_not_touch_queries(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "t.sql"
    f.write_text("CREATE TABLE t (id INT);")
    mgr.queries["unrelated"] = "SELECT 1"
    mgr._save_queries()
    mgr.scan("ddl")
    mgr.delete_files("t.sql", subdir="ddl")
    assert mgr.queries["unrelated"] == "SELECT 1"


def test_delete_files_missing_file_does_not_raise(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "ghost.sql"
    f.write_text("CREATE TABLE t (id INT);")
    mgr.scan("ddl")
    f.unlink()
    mgr.delete_files("ghost.sql", subdir="ddl")
    entry = next(e for e in mgr.log if "ghost.sql" in e.file_path)
    assert entry.last_action == "deleted"


# ---------------------------------------------------------------------------
# Manager.run_new_files
# ---------------------------------------------------------------------------

def test_run_new_files_loads_queries(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    assert mgr.queries["get_users"] == "SELECT * FROM users;"


def test_run_new_files_queries_written_to_disk(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    data = json.loads(mgr._queries_path.read_text())
    assert data["get_users"] == "SELECT * FROM users;"


def test_run_new_files_skips_already_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    mgr.queries = {}
    mgr.run_new_files("queries")
    assert "get_users" not in mgr.queries


def test_run_new_files_marks_log_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    entry = next(e for e in mgr.log if "get_users.sql" in e.file_path)
    assert entry.last_action == "RUN"


def test_run_new_files_ddl_executes_on_current_connector(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    conn = _mock_conn()
    mgr._current_connector = conn
    mgr.run_new_files("ddl")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE foo (id INT);")
    conn.commit.assert_called_once()


def test_run_new_files_ddl_named_connector(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    conn = _mock_conn()
    mgr.connections["mydb"] = conn
    mgr.run_new_files("ddl", name="mydb")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE foo (id INT);")


def test_run_new_files_databases_by_dirname(mgr, tmp_path):
    d = tmp_path / "sql" / "databases" / "mydb"
    d.mkdir()
    f = d / "setup.sql"
    f.write_text("CREATE TABLE t (id INT);")
    conn = _mock_conn()
    mgr.connections["mydb"] = conn
    mgr.run_new_files("databases")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE t (id INT);")


def test_run_new_files_databases_by_filestem(mgr, tmp_path):
    f = tmp_path / "sql" / "databases" / "mydb.sql"
    f.write_text("CREATE TABLE t (id INT);")
    conn = _mock_conn()
    mgr.connections["mydb"] = conn
    mgr.run_new_files("databases")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE t (id INT);")


def test_run_new_files_databases_fallback_to_current_connector(mgr, tmp_path):
    d = tmp_path / "sql" / "databases" / "unknown"
    d.mkdir()
    f = d / "setup.sql"
    f.write_text("CREATE TABLE t (id INT);")
    conn = _mock_conn()
    mgr._current_connector = conn
    mgr.run_new_files("databases")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE t (id INT);")


def test_run_new_files_ddl_no_connection_skips_log_entry(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.run_new_files("ddl")
    assert mgr.log == []


def test_run_new_files_no_connection_warns(mgr, tmp_path):
    (tmp_path / "sql" / "ddl" / "t.sql").write_text("CREATE TABLE t (id INT);")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mgr.run_new_files("ddl")
    assert any("t.sql" in str(warning.message) for warning in w)


def test_run_new_files_sql_error_rolls_back_and_continues(mgr, tmp_path):
    (tmp_path / "sql" / "ddl" / "bad.sql").write_text("INVALID SQL;")
    (tmp_path / "sql" / "ddl" / "good.sql").write_text("CREATE TABLE t (id INT);")
    conn = _mock_conn()
    def execute_side_effect(sql):
        if "INVALID" in sql:
            raise Exception("syntax error")
    _cursor(conn).execute.side_effect = execute_side_effect
    mgr._current_connector = conn
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mgr.run_new_files("ddl")
    conn.rollback.assert_called_once()
    assert conn.commit.call_count == 1
    assert any("bad.sql" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# Manager._resolve_entries
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr_with_entry(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    return mgr, f


def test_resolve_by_file_id(mgr_with_entry):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    result = mgr._resolve_entries(entry.file_id)
    assert result == [entry]


def test_resolve_by_full_path(mgr_with_entry):
    mgr, f = mgr_with_entry
    result = mgr._resolve_entries(str(f))
    assert result == [mgr.log[0]]


def test_resolve_by_filename(mgr_with_entry):
    mgr, f = mgr_with_entry
    result = mgr._resolve_entries("create_table.sql")
    assert result == [mgr.log[0]]


def test_resolve_by_stem(mgr_with_entry):
    mgr, f = mgr_with_entry
    result = mgr._resolve_entries("create_table")
    assert result == [mgr.log[0]]


def test_resolve_by_path_object(mgr_with_entry):
    mgr, f = mgr_with_entry
    result = mgr._resolve_entries(f)
    assert result == [mgr.log[0]]


def test_resolve_unknown_returns_empty(mgr):
    assert mgr._resolve_entries(999) == []
    assert mgr._resolve_entries("nonexistent") == []


def test_resolve_list_of_ids(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "ddl" / name).write_text("SELECT 1;")
    mgr.scan("ddl")
    ids = [e.file_id for e in mgr.log]
    result = mgr._resolve_entries(ids)
    assert len(result) == 2


def test_resolve_list_of_names(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "ddl" / name).write_text("SELECT 1;")
    mgr.scan("ddl")
    result = mgr._resolve_entries(["a.sql", "b.sql"])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Manager.set_run_status
# ---------------------------------------------------------------------------

def test_set_run_status_default_is_run(mgr_with_entry):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    mgr.set_run_status(entry.file_id)
    assert entry.last_action == "RUN"


def test_set_run_status_custom_valid_action(mgr_with_entry):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    mgr.set_run_status(entry.file_id, run="SCANNED")
    assert entry.last_action == "SCANNED"


def test_set_run_status_all_valid_actions(mgr_with_entry):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    for action in Manager.VALID_ACTIONS:
        mgr.set_run_status(entry.file_id, run=action)
        assert entry.last_action == action


def test_set_run_status_invalid_action_raises(mgr_with_entry):
    mgr, f = mgr_with_entry
    with pytest.raises(ValueError, match="Invalid action"):
        mgr.set_run_status(mgr.log[0].file_id, run="INVALID")


def test_set_run_status_updates_timestamp(mgr_with_entry):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    old_ts = entry.date_last_action
    mgr.set_run_status(entry.file_id, run="RUN")
    assert entry.date_last_action >= old_ts


def test_set_run_status_persists_log(mgr_with_entry, tmp_path):
    mgr, f = mgr_with_entry
    entry = mgr.log[0]
    mgr.set_run_status(entry.file_id, run="RUN")
    mgr2 = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    assert mgr2.log[0].last_action == "RUN"


def test_set_run_status_by_name(mgr_with_entry):
    mgr, f = mgr_with_entry
    mgr.set_run_status("create_table", run="WIPED")
    assert mgr.log[0].last_action == "WIPED"


def test_set_run_status_list_of_ids(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "ddl" / name).write_text("SELECT 1;")
    mgr.scan("ddl")
    ids = [e.file_id for e in mgr.log]
    mgr.set_run_status(ids, run="RUN")
    assert all(e.last_action == "RUN" for e in mgr.log)


# ---------------------------------------------------------------------------
# Manager.rerun_files
# ---------------------------------------------------------------------------

def test_rerun_query_by_id(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    f.write_text("SELECT id FROM users;")
    entry = next(e for e in mgr.log if "get_users" in e.file_path)
    mgr.rerun_files(entry.file_id)
    assert mgr.queries["get_users"] == "SELECT id FROM users;"


def test_rerun_query_by_name(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT * FROM users;")
    mgr.run_new_files("queries")
    f.write_text("SELECT id FROM users;")
    mgr.rerun_files("get_users")
    assert mgr.queries["get_users"] == "SELECT id FROM users;"


def test_rerun_reruns_even_if_already_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "get_users.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    f.write_text("SELECT 2;")
    mgr.rerun_files("get_users")
    assert mgr.queries["get_users"] == "SELECT 2;"


def test_rerun_ddl(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    entry = mgr.log[0]
    conn = _mock_conn()
    mgr._current_connector = conn
    mgr.rerun_files(entry.file_id)
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE foo (id INT);")
    conn.commit.assert_called_once()


def test_rerun_ddl_named_connector(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    conn = _mock_conn()
    mgr.connections["mydb"] = conn
    mgr.rerun_files("create_table", name="mydb")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE foo (id INT);")


def test_rerun_no_connection_warns(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "t.sql"
    f.write_text("CREATE TABLE t (id INT);")
    mgr.scan("ddl")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mgr.rerun_files()
    assert any("t.sql" in str(warning.message) for warning in w)


def test_rerun_returns_only_executed(mgr, tmp_path):
    (tmp_path / "sql" / "queries" / "a.sql").write_text("SELECT 1;")
    (tmp_path / "sql" / "queries" / "b.sql").write_text("SELECT 2;")
    mgr.scan()
    mgr.set_run_status(mgr.log[0].file_id, run="RUN")
    result = mgr.rerun_files(skip_run=True)
    assert len(result) == 1
    assert result[0].last_action == "RUN"


def test_rerun_skips_missing_file(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE foo (id INT);")
    mgr.scan("ddl")
    mgr.set_run_status("create_table", run="RUN")  # force to RUN so skip is meaningful
    entry = mgr.log[0]
    assert entry.last_action == "RUN"
    f.unlink()
    result = mgr.rerun_files(entry.file_id)
    assert result == []
    assert entry.last_action == "RUN"  # skip on missing file must not change status


def test_rerun_marks_log_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.scan("queries")
    mgr.rerun_files("q")
    assert mgr.log[0].last_action == "RUN"


def test_rerun_persists_queries(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    f.write_text("SELECT 2;")
    mgr.rerun_files("q")
    reloaded = mgr._read_queries()
    assert reloaded["q"] == "SELECT 2;"


def test_rerun_files_none_reruns_all(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 1;")
    mgr.scan()
    mgr.rerun_files()
    assert all(e.last_action == "RUN" for e in mgr.log)


def test_rerun_files_none_reruns_already_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    f.write_text("SELECT 2;")
    mgr.rerun_files()
    assert mgr.queries["q"] == "SELECT 2;"


def test_rerun_files_skip_run_skips_run_entries(mgr, tmp_path):
    (tmp_path / "sql" / "queries" / "a.sql").write_text("SELECT 1;")
    (tmp_path / "sql" / "queries" / "b.sql").write_text("SELECT 2;")
    mgr.scan()
    mgr.set_run_status(mgr.log[0].file_id, run="RUN")
    mgr.queries = {}
    mgr.rerun_files(skip_run=True)
    assert len(mgr.queries) == 1


def test_rerun_files_skip_run_false_runs_all(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 1;")
    mgr.run_new_files("queries")
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 2;")
    mgr.rerun_files(skip_run=False)
    assert all(mgr.queries[k] == "SELECT 2;" for k in ("a", "b"))


def test_rerun_files_skip_run_with_explicit_list(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 1;")
    mgr.run_new_files("queries")
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 99;")
    ids = [e.file_id for e in mgr.log]
    result = mgr.rerun_files(ids, skip_run=True)
    assert result == []
    assert all(mgr.queries[k] == "SELECT 1;" for k in ("a", "b"))


# ---------------------------------------------------------------------------
# Manager.connection_status
# ---------------------------------------------------------------------------

def test_connection_status_empty(mgr):
    assert mgr.connection_status() == {}


def test_connection_status_open(mgr):
    m = MagicMock()
    m.closed = 0
    mgr.connections["db1"] = m
    assert mgr.connection_status() == {"db1": True}


def test_connection_status_closed(mgr):
    m = MagicMock()
    m.closed = 1
    mgr.connections["db1"] = m
    assert mgr.connection_status()["db1"] is False


def test_connection_status_mixed(mgr):
    open_conn, closed_conn = MagicMock(), MagicMock()
    open_conn.closed = 0
    closed_conn.closed = 2
    mgr.connections["a"] = open_conn
    mgr.connections["b"] = closed_conn
    result = mgr.connection_status()
    assert result == {"a": True, "b": False}


def test_connection_status_named(mgr):
    m = MagicMock()
    m.closed = 0
    mgr.connections["db1"] = m
    mgr.connections["db2"] = MagicMock()
    result = mgr.connection_status("db1")
    assert list(result.keys()) == ["db1"]
    assert result["db1"] is True


def test_connection_status_unknown_raises(mgr):
    with pytest.raises(KeyError, match="nonexistent"):
        mgr.connection_status("nonexistent")


# ---------------------------------------------------------------------------
# Manager.execute_query
# ---------------------------------------------------------------------------

def test_execute_query_single(mgr):
    mgr.queries["q1"] = "SELECT 1"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.return_value = [(1,)]
    mgr._current_connector = conn
    result = mgr.execute_query("q1")
    assert result == [(1,)]
    conn.cursor.return_value.execute.assert_called_once_with("SELECT 1")



def test_execute_query_list(mgr):
    mgr.queries["q1"] = "SELECT 1"
    mgr.queries["q2"] = "SELECT 2"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.side_effect = [[(1,)], [(2,)]]
    mgr._current_connector = conn
    result = mgr.execute_query(["q1", "q2"])
    assert result == [[(1,)], [(2,)]]


def test_execute_query_named_connector(mgr):
    mgr.queries["q1"] = "SELECT 1"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.return_value = [(1,)]
    mgr.connections["mydb"] = conn
    result = mgr.execute_query("q1", connector="mydb")
    conn.cursor.return_value.execute.assert_called_once_with("SELECT 1")
    assert result == [(1,)]


def test_execute_query_missing_query_raises(mgr):
    conn = _mock_conn()
    mgr._current_connector = conn
    with pytest.raises(KeyError):
        mgr.execute_query("nonexistent")


def test_execute_query_kwargs_expanded_into_format_string(mgr):
    mgr.queries["q1"] = "SELECT * FROM t WHERE id = {user_id} AND status = '{status}'"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.return_value = [(1, "active")]
    mgr._current_connector = conn
    result = mgr.execute_query("q1", user_id=42, status="active")
    conn.cursor.return_value.execute.assert_called_once_with(
        "SELECT * FROM t WHERE id = 42 AND status = 'active'"
    )
    assert result == [(1, "active")]


def test_execute_query_list_kwargs_expanded(mgr):
    mgr.queries["q1"] = "SELECT {col} FROM t"
    mgr.queries["q2"] = "SELECT {col} FROM u"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.side_effect = [[(1,)], [(2,)]]
    mgr._current_connector = conn
    result = mgr.execute_query(["q1", "q2"], col="id")
    assert conn.cursor.return_value.execute.call_args_list[0][0][0] == "SELECT id FROM t"
    assert conn.cursor.return_value.execute.call_args_list[1][0][0] == "SELECT id FROM u"
    assert result == [[(1,)], [(2,)]]


def test_execute_query_closes_cursor(mgr):
    mgr.queries["q1"] = "SELECT 1"
    conn = _mock_conn()
    conn.cursor.return_value.fetchall.return_value = []
    mgr._current_connector = conn
    mgr.execute_query("q1")
    conn.cursor.return_value.close.assert_called_once()


def test_execute_query_closes_cursor_on_error(mgr):
    mgr.queries["q1"] = "SELECT 1"
    conn = _mock_conn()
    conn.cursor.return_value.execute.side_effect = Exception("DB error")
    mgr._current_connector = conn
    with pytest.raises(Exception, match="DB error"):
        mgr.execute_query("q1")
    conn.cursor.return_value.close.assert_called_once()


def test_execute_query_no_connection_raises(mgr):
    mgr.queries["q1"] = "SELECT 1"
    with pytest.raises(RuntimeError, match="No active connection"):
        mgr.execute_query("q1")


# ---------------------------------------------------------------------------
# Manager.run_files
# ---------------------------------------------------------------------------

def test_run_files_query_by_id(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.scan("queries")
    entry = mgr.log[0]
    result = mgr.run_files(entry.file_id)
    assert result == [entry]
    assert entry.last_action == "RUN"
    assert mgr.queries["q"] == "SELECT 1;"


def test_run_files_ddl_by_id(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE t (id INT);")
    mgr.scan("ddl")
    conn = _mock_conn()
    mgr._current_connector = conn
    entry = mgr.log[0]
    result = mgr.run_files(entry.file_id)
    assert result == [entry]
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE t (id INT);")
    conn.commit.assert_called_once()


def test_run_files_ddl_named_connector(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "create_table.sql"
    f.write_text("CREATE TABLE t (id INT);")
    mgr.scan("ddl")
    conn = _mock_conn()
    mgr.connections["mydb"] = conn
    mgr.run_files(mgr.log[0].file_id, name="mydb")
    _cursor(conn).execute.assert_called_once_with("CREATE TABLE t (id INT);")


def test_run_files_skips_already_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    mgr.queries = {}
    result = mgr.run_files(mgr.log[0].file_id)
    assert result == []
    assert "q" not in mgr.queries


def test_run_files_force_reruns_already_run(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.run_new_files("queries")
    f.write_text("SELECT 2;")
    mgr.run_files(mgr.log[0].file_id, force=True)
    assert mgr.queries["q"] == "SELECT 2;"


def test_run_files_skips_missing_file(mgr, tmp_path):
    f = tmp_path / "sql" / "ddl" / "t.sql"
    f.write_text("SELECT 1;")
    mgr.scan("ddl")
    f.unlink()
    result = mgr.run_files(mgr.log[0].file_id)
    assert result == []


def test_run_files_list_of_ids(mgr, tmp_path):
    for name in ("a.sql", "b.sql"):
        (tmp_path / "sql" / "queries" / name).write_text("SELECT 1;")
    mgr.scan()
    ids = [e.file_id for e in mgr.log]
    result = mgr.run_files(ids)
    assert len(result) == 2
    assert all(e.last_action == "RUN" for e in result)


def test_run_files_partial_skip(mgr, tmp_path):
    (tmp_path / "sql" / "queries" / "a.sql").write_text("SELECT 1;")
    (tmp_path / "sql" / "queries" / "b.sql").write_text("SELECT 2;")
    mgr.scan()
    mgr.set_run_status(mgr.log[0].file_id, run="RUN")
    ids = [e.file_id for e in mgr.log]
    result = mgr.run_files(ids)
    assert len(result) == 1


def test_run_files_persists_log(mgr, tmp_path):
    f = tmp_path / "sql" / "queries" / "q.sql"
    f.write_text("SELECT 1;")
    mgr.scan("queries")
    mgr.run_files(mgr.log[0].file_id)
    m2 = Manager(log_path=tmp_path / "test.log.json", sql_dir=tmp_path / "sql")
    assert m2.log[0].last_action == "RUN"


def test_run_files_unknown_id_returns_empty(mgr):
    result = mgr.run_files(999)
    assert result == []


# ---------------------------------------------------------------------------
# Manager.list_files
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr_populated(mgr, tmp_path):
    (tmp_path / "sql" / "ddl" / "a.sql").write_text("SELECT 1;")
    (tmp_path / "sql" / "ddl" / "b.sql").write_text("SELECT 2;")
    (tmp_path / "sql" / "queries" / "q.sql").write_text("SELECT 3;")
    mgr.scan()
    mgr.set_run_status("a", run="RUN")
    return mgr


def test_list_files_no_filter_returns_all(mgr_populated):
    assert len(mgr_populated.list_files()) == 3


def test_list_files_by_subdir_single(mgr_populated, tmp_path):
    result = mgr_populated.list_files(subdir="ddl")
    assert len(result) == 2
    assert all("ddl" in e.file_path for e in result)


def test_list_files_by_subdir_list(mgr_populated, tmp_path):
    result = mgr_populated.list_files(subdir=["ddl", "queries"])
    assert len(result) == 3


def test_list_files_by_subdir_excludes_others(mgr_populated, tmp_path):
    result = mgr_populated.list_files(subdir="queries")
    assert len(result) == 1
    assert "queries" in result[0].file_path


def test_list_files_by_status_single(mgr_populated):
    result = mgr_populated.list_files(status="RUN")
    assert all(e.last_action == "RUN" for e in result)
    assert len(result) == 1


def test_list_files_by_status_list(mgr_populated):
    result = mgr_populated.list_files(status=["RUN", "SCANNED"])
    assert len(result) == 3


def test_list_files_subdir_and_status(mgr_populated):
    result = mgr_populated.list_files(subdir="ddl", status="SCANNED")
    assert len(result) == 1
    assert "b.sql" in result[0].file_path


def test_list_files_no_match_returns_empty(mgr_populated):
    assert mgr_populated.list_files(status="deleted") == []


def test_list_files_empty_log(mgr):
    assert mgr.list_files() == []
