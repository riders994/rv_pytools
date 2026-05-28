from dataclasses import dataclass

# Add default/utility classes here


@dataclass
class ConnectionManagerLogEntry:
    file_id: int
    file_path: str
    date_scanned: str
    date_last_action: str
    last_action: str
