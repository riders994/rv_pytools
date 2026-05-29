from dataclasses import dataclass

__all__ = ["ConnectionManagerLogEntry"]


@dataclass
class ConnectionManagerLogEntry:
    file_id: int
    file_path: str
    date_scanned: str
    date_last_action: str
    last_action: str
