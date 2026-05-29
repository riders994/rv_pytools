import psycopg2
import psycopg2.extensions


def connect(params: dict) -> psycopg2.extensions.connection:
    """
    Function that creates a psycopg connection object based on given params
    :param params: Connection details
    :return: connection object
    """
    return psycopg2.connect(**params)


class ConnectionManager:
    """

    """

    def __init__(self):
        self.connections: dict[str, psycopg2.extensions.connection] = dict()
        self.last_connector: psycopg2.extensions.connection | None = None
        self._current_connector: psycopg2.extensions.connection | None = None

    def connect(self, name: str, params: dict) -> psycopg2.extensions.connection:
        conn = psycopg2.connect(**params)
        self.connections[name] = conn
        self.set_last_connection(conn)
        return conn

    def set_last_connection(self, conn: psycopg2.extensions.connection) -> None:
        self.last_connector = conn

    def set_connection(self, name: str | None = None) -> psycopg2.extensions.connection | None:
        if name is not None:
            found = self.connections.get(name)
            if found is not None:
                self._current_connector = found
        if self._current_connector is None:
            self._current_connector = self.last_connector
        return self._current_connector

    @property
    def current_connector(self) -> psycopg2.extensions.connection | None:
        if self._current_connector is None:
            self._current_connector = self.last_connector
        return self._current_connector
