from rv_pytools.classes import ConnectionManagerLogEntry


def test_log_entry_construction():
    entry = ConnectionManagerLogEntry(
        file_id=1,
        file_path="/path/to/file.sql",
        date_scanned="2024-01-01T00:00:00",
        date_last_action="2024-01-01T00:00:00",
        last_action="SCANNED",
    )
    assert entry.file_id == 1
    assert entry.file_path == "/path/to/file.sql"
    assert entry.date_scanned == "2024-01-01T00:00:00"
    assert entry.date_last_action == "2024-01-01T00:00:00"
    assert entry.last_action == "SCANNED"


def test_log_entry_equality():
    a = ConnectionManagerLogEntry(1, "/a.sql", "2024-01-01T00:00:00", "2024-01-01T00:00:00", "RUN")
    b = ConnectionManagerLogEntry(1, "/a.sql", "2024-01-01T00:00:00", "2024-01-01T00:00:00", "RUN")
    assert a == b


def test_log_entry_inequality():
    a = ConnectionManagerLogEntry(1, "/a.sql", "2024-01-01T00:00:00", "2024-01-01T00:00:00", "RUN")
    b = ConnectionManagerLogEntry(2, "/a.sql", "2024-01-01T00:00:00", "2024-01-01T00:00:00", "RUN")
    assert a != b


def test_log_entry_mutation():
    entry = ConnectionManagerLogEntry(1, "/a.sql", "2024-01-01T00:00:00", "2024-01-01T00:00:00", "SCANNED")
    entry.last_action = "RUN"
    assert entry.last_action == "RUN"


def test_log_entry_all_action_values():
    for action in ("SCANNED", "RUN", "deleted", "WIPED"):
        entry = ConnectionManagerLogEntry(1, "/a.sql", "t", "t", action)
        assert entry.last_action == action
