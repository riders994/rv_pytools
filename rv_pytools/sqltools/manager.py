from dataclasses import asdict
from pathlib import Path
import json
import time
import tomllib
import warnings

from .connections import ConnectionManager
from ..classes import ConnectionManagerLogEntry


class Manager(ConnectionManager):
    def __init__(
        self,
        log_path: str | Path | None = None,
        sql_dir: str | Path | None = None,
        config_path: str | Path | None = None,
    ):
        super().__init__()

        self.config: dict = self._load_config(config_path) if config_path else {}

        cfg_paths = self.config.get("paths", {})
        _log = log_path or cfg_paths.get("log_path") or "manager.log.json"
        _sql = sql_dir or cfg_paths.get("sql_dir") or "sql"
        self.log_path: Path = Path(_log)
        self.sql_dir: Path = Path(_sql).resolve()
        self.db_defaults: dict = self.config.get("database", {})

        self._init_paths()
        self.log: list[ConnectionManagerLogEntry] = self._read_log()
        self.queries: dict[str, str] = self._read_queries()

    def connection_status(self, name: str | None = None) -> dict[str, bool]:
        if name is not None:
            if name not in self.connections:
                raise KeyError(f"No connection named {name!r}")
            conns = {name: self.connections[name]}
        else:
            conns = self.connections
        return {n: conn.closed == 0 for n, conn in conns.items()}

    @staticmethod
    def _load_config(config_path: str | Path) -> dict:
        with open(config_path, "rb") as f:
            return tomllib.load(f)

    def _init_paths(self) -> None:
        for subdir in ("databases", "ddl", "queries"):
            (self.sql_dir / subdir).mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # --- log methods ---

    def _read_log(self) -> list[ConnectionManagerLogEntry]:
        if not self.log_path.exists():
            return []
        content = self.log_path.read_text().strip()
        if not content:
            return []
        return [ConnectionManagerLogEntry(**entry) for entry in json.loads(content)]

    def _next_file_id(self) -> int:
        return max((e.file_id for e in self.log), default=0) + 1

    def add_log_entry(self, file_path: str, action: str) -> ConnectionManagerLogEntry:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        entry = ConnectionManagerLogEntry(
            file_id=self._next_file_id(),
            file_path=file_path,
            date_scanned=ts,
            date_last_action=ts,
            last_action=action,
        )
        self.log.append(entry)
        return entry

    def update_log_entry(self, file_id: int, action: str) -> ConnectionManagerLogEntry | None:
        for entry in self.log:
            if entry.file_id == file_id:
                entry.date_last_action = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                entry.last_action = action
                return entry
        return None

    def save_log(self) -> None:
        self.log_path.write_text(json.dumps([asdict(e) for e in self.log], indent=2))

    # --- query methods ---

    @property
    def _queries_path(self) -> Path:
        return self.sql_dir / "queries" / "_queries.json"

    def _read_queries(self) -> dict[str, str]:
        if not self._queries_path.exists():
            return {}
        content = self._queries_path.read_text().strip()
        if not content:
            return {}
        return json.loads(content)

    def _save_queries(self) -> None:
        self._queries_path.write_text(json.dumps(self.queries, indent=2))

    def execute_query(self, name: str | list[str], connector: str | None = None, **kwargs) -> list:
        if connector is None:
            conn = self.current_connector
        else:
            conn = self.connections[connector]
        if conn is None:
            raise RuntimeError("No active connection. Call connect() or set_connection() first.")
        cursor = None
        try:
            cursor = conn.cursor()
            if isinstance(name, list):
                res = []
                for n in name:
                    q = self.queries[n]
                    cursor.execute(q.format(**kwargs))
                    res.append(cursor.fetchall())
            else:
                q = self.queries[name]
                cursor.execute(q.format(**kwargs))
                res = cursor.fetchall()
        finally:
            if cursor is not None:
                cursor.close()
        return res

    # --- file methods ---

    def delete_files(
        self,
        files: str | Path | list[str | Path],
        subdir: str | None = None,
    ) -> list[ConnectionManagerLogEntry]:
        if isinstance(files, (str, Path)):
            files = [files]

        resolved: list[Path] = []
        for f in files:
            if subdir is not None:
                resolved.append(self.sql_dir / subdir / f)
            else:
                resolved.append(Path(f))

        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        updated: list[ConnectionManagerLogEntry] = []

        for path in resolved:
            path.unlink(missing_ok=True)
            str_path = str(path)
            existing = next((e for e in self.log if e.file_path == str_path), None)
            if existing:
                existing.date_last_action = ts
                existing.last_action = "deleted"
                updated.append(existing)
            else:
                entry = ConnectionManagerLogEntry(
                    file_id=self._next_file_id(),
                    file_path=str_path,
                    date_scanned=ts,
                    date_last_action=ts,
                    last_action="deleted",
                )
                self.log.append(entry)
                updated.append(entry)

        queries_updated = any(
            Path(e.file_path).is_relative_to(self.sql_dir / "queries") for e in updated
        )
        if queries_updated:
            for entry in updated:
                p = Path(entry.file_path)
                if p.is_relative_to(self.sql_dir / "queries"):
                    self.queries.pop(p.stem, None)
            self._save_queries()

        self.save_log()
        return updated

    @staticmethod
    def _exec_sql(conn, sql: str, file_path: str) -> bool:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            return True
        except Exception as exc:
            conn.rollback()
            warnings.warn(f"Failed to execute {file_path}: {exc}", stacklevel=3)
            return False

    def _collect_sql_files(self, subdir: str) -> list[Path]:
        base = self.sql_dir / subdir
        if not base.exists():
            return []
        extensions = {".sql", ".txt"}
        if subdir == "databases":
            files = []
            for item in base.iterdir():
                if item.is_file() and item.suffix in extensions:
                    files.append(item)
                elif item.is_dir():
                    files.extend(f for f in item.iterdir() if f.is_file() and f.suffix in extensions)
            return files
        return [f for f in base.iterdir() if f.is_file() and f.suffix in extensions]

    def run_new_files(
        self,
        subdir: str | None = None,
        name: str | None = None,
    ) -> list[ConnectionManagerLogEntry]:
        subdirs = [subdir] if subdir else ["databases", "ddl", "queries"]
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        updated: list[ConnectionManagerLogEntry] = []
        queries_updated = False

        for sd in subdirs:
            for path in self._collect_sql_files(sd):
                str_path = str(path)
                existing = next((e for e in self.log if e.file_path == str_path), None)
                if existing and existing.last_action == "RUN":
                    continue

                sql = path.read_text()
                executed = True

                if sd == "databases":
                    databases_root = self.sql_dir / "databases"
                    conn_name = path.parent.name if path.parent != databases_root else path.stem
                    conn = self.connections.get(conn_name) or self.current_connector
                    if conn:
                        executed = self._exec_sql(conn, sql, str_path)
                    else:
                        warnings.warn(f"No connection available for {str_path}", stacklevel=2)
                        executed = False

                elif sd == "ddl":
                    conn = self.connections.get(name) if name else self.current_connector
                    if conn:
                        executed = self._exec_sql(conn, sql, str_path)
                    else:
                        warnings.warn(f"No connection available for {str_path}", stacklevel=2)
                        executed = False

                elif sd == "queries":
                    self.queries[path.stem] = sql
                    queries_updated = True
                    executed = True

                if executed:
                    if existing:
                        existing.date_last_action = ts
                        existing.last_action = "RUN"
                        updated.append(existing)
                    else:
                        entry = ConnectionManagerLogEntry(
                            file_id=self._next_file_id(),
                            file_path=str_path,
                            date_scanned=ts,
                            date_last_action=ts,
                            last_action="RUN",
                        )
                        self.log.append(entry)
                        updated.append(entry)

        if queries_updated:
            self._save_queries()
        self.save_log()
        return updated

    def _resolve_entries(
        self,
        files: int | str | Path | list[int | str | Path],
    ) -> list[ConnectionManagerLogEntry]:
        if not isinstance(files, list):
            files = [files]
        entries = []
        for f in files:
            if isinstance(f, int):
                entry = next((e for e in self.log if e.file_id == f), None)
            else:
                needle = str(f)
                entry = next(
                    (e for e in self.log
                     if e.file_path == needle
                     or Path(e.file_path).name == needle
                     or Path(e.file_path).stem == needle),
                    None,
                )
            if entry is not None:
                entries.append(entry)
        return entries

    VALID_ACTIONS = {"RUN", "SCANNED", "deleted", "WIPED"}

    def set_run_status(
        self,
        files: int | str | Path | list[int | str | Path],
        run: str = "RUN",
    ) -> list[ConnectionManagerLogEntry]:
        if run not in self.VALID_ACTIONS:
            raise ValueError(f"Invalid action {run!r}. Must be one of: {sorted(self.VALID_ACTIONS)}")
        entries = self._resolve_entries(files)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        for entry in entries:
            entry.last_action = run
            entry.date_last_action = ts
        self.save_log()
        return entries

    def rerun_files(
        self,
        files: int | str | Path | list[int | str | Path] | None = None,
        name: str | None = None,
        skip_run: bool = False,
    ) -> list[ConnectionManagerLogEntry]:
        entries = self.log if files is None else self._resolve_entries(files)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        databases_root = self.sql_dir / "databases"
        queries_updated = False
        updated: list[ConnectionManagerLogEntry] = []

        for entry in entries:
            if skip_run and entry.last_action == "RUN":
                continue

            path = Path(entry.file_path)
            if not path.exists():
                continue

            sql = path.read_text()
            executed = True

            if path.is_relative_to(self.sql_dir / "databases"):
                conn_name = path.parent.name if path.parent != databases_root else path.stem
                conn = self.connections.get(conn_name) or self.current_connector
                if conn:
                    executed = self._exec_sql(conn, sql, entry.file_path)
                else:
                    warnings.warn(f"No connection available for {entry.file_path}", stacklevel=2)
                    executed = False

            elif path.is_relative_to(self.sql_dir / "ddl"):
                conn = self.connections.get(name) if name else self.current_connector
                if conn:
                    executed = self._exec_sql(conn, sql, entry.file_path)
                else:
                    warnings.warn(f"No connection available for {entry.file_path}", stacklevel=2)
                    executed = False

            elif path.is_relative_to(self.sql_dir / "queries"):
                self.queries[path.stem] = sql
                queries_updated = True
                executed = True

            if executed:
                entry.date_last_action = ts
                entry.last_action = "RUN"
                updated.append(entry)

        if queries_updated:
            self._save_queries()
        self.save_log()
        return updated

    def run_files(
        self,
        files: int | str | Path | list[int | str | Path],
        name: str | None = None,
        force: bool = False,
    ) -> list[ConnectionManagerLogEntry]:
        entries = self._resolve_entries(files)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        databases_root = self.sql_dir / "databases"
        queries_updated = False
        updated: list[ConnectionManagerLogEntry] = []

        for entry in entries:
            if not force and entry.last_action == "RUN":
                continue

            path = Path(entry.file_path)
            if not path.exists():
                continue

            sql = path.read_text()
            executed = True

            if path.is_relative_to(self.sql_dir / "databases"):
                conn_name = path.parent.name if path.parent != databases_root else path.stem
                conn = self.connections.get(conn_name) or self.current_connector
                if conn:
                    executed = self._exec_sql(conn, sql, entry.file_path)
                else:
                    warnings.warn(f"No connection available for {entry.file_path}", stacklevel=2)
                    executed = False

            elif path.is_relative_to(self.sql_dir / "ddl"):
                conn = self.connections.get(name) if name else self.current_connector
                if conn:
                    executed = self._exec_sql(conn, sql, entry.file_path)
                else:
                    warnings.warn(f"No connection available for {entry.file_path}", stacklevel=2)
                    executed = False

            elif path.is_relative_to(self.sql_dir / "queries"):
                self.queries[path.stem] = sql
                queries_updated = True
                executed = True

            if executed:
                entry.date_last_action = ts
                entry.last_action = "RUN"
                updated.append(entry)

        if queries_updated:
            self._save_queries()
        self.save_log()
        return updated

    def list_files(
        self,
        subdir: str | list[str] | None = None,
        status: str | list[str] | None = None,
    ) -> list[ConnectionManagerLogEntry]:
        entries = self.log

        if subdir is not None:
            subdirs = [subdir] if isinstance(subdir, str) else subdir
            bases = [self.sql_dir / sd for sd in subdirs]
            entries = [e for e in entries if any(Path(e.file_path).is_relative_to(b) for b in bases)]

        if status is not None:
            statuses = {status} if isinstance(status, str) else set(status)
            entries = [e for e in entries if e.last_action in statuses]

        return entries

    def scan(self, subdir: str | None = None) -> list[ConnectionManagerLogEntry]:

        subdirs = [subdir] if subdir else ["databases", "ddl", "queries"]
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

        found: list[Path] = []
        for sd in subdirs:
            found.extend(self._collect_sql_files(sd))

        found_str = {str(f) for f in found}
        updated: list[ConnectionManagerLogEntry] = []

        for path in found:
            str_path = str(path)
            existing = next((e for e in self.log if e.file_path == str_path), None)
            if existing:
                existing.date_last_action = ts
                if existing.last_action != "RUN":
                    existing.last_action = "SCANNED"
                updated.append(existing)
            else:
                entry = ConnectionManagerLogEntry(
                    file_id=self._next_file_id(),
                    file_path=str_path,
                    date_scanned=ts,
                    date_last_action=ts,
                    last_action="SCANNED",
                )
                self.log.append(entry)
                updated.append(entry)

        scanned_bases = [self.sql_dir / sd for sd in subdirs]
        for entry in self.log:
            if entry.last_action in ("deleted", "WIPED"):
                continue
            entry_path = Path(entry.file_path)
            in_scope = any(entry_path.is_relative_to(base) for base in scanned_bases)
            if in_scope and entry.file_path not in found_str:
                entry.date_last_action = ts
                entry.last_action = "WIPED"
                warnings.warn(f"File missing from scan: {entry.file_path}", stacklevel=2)

        self.save_log()
        return updated
