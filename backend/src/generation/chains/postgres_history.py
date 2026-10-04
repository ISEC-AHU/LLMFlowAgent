"""
Lightweight PostgreSQL chat-history persistence.

This implementation replaces the deprecated
``langchain_community.PostgresChatMessageHistory`` with a direct psycopg3 and
``langchain_core`` implementation. It reuses the existing
``chat_message_store`` schema (``id integer / session_id text / message
jsonb``), so no data migration or deprecation warning is required.
"""

import json
import os
from typing import List, Optional

import psycopg
from psycopg.conninfo import make_conninfo
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
)

_DEFAULT_TABLE = "chat_message_store"


def _database_connection_string() -> str:
    """Build a psycopg connection string from the deployment environment."""
    return make_conninfo(
        dbname=os.getenv("DB_NAME", "llmflowagent"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


class PostgresChatMessageHistory(BaseChatMessageHistory):
    """Psycopg3-backed chat history compatible with the legacy interface.

    Args:
        session_id: Arbitrary session identifier compatible with existing data.
        connection_string: PostgreSQL connection string.
        table_name: Table used to store messages.
    """

    def __init__(
        self,
        session_id: str,
        connection_string: Optional[str] = None,
        table_name: str = _DEFAULT_TABLE,
    ) -> None:
        self.session_id = session_id
        self.connection_string = connection_string or _database_connection_string()
        self.table_name = table_name

    @property
    def messages(self) -> List[BaseMessage]:
        """Return all messages for the current session in primary-key order."""
        query = (
            f"SELECT message FROM {self.table_name} "
            f"WHERE session_id = %s ORDER BY id ASC"
        )
        with psycopg.connect(self.connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (self.session_id,))
                rows = cur.fetchall()
        # Psycopg3 returns the JSONB message column as a dictionary by default.
        raw = [{"type": row[0]["type"], "data": row[0]["data"]} for row in rows]
        return messages_from_dict(raw) if raw else []

    def add_message(self, message: BaseMessage) -> None:
        """Append one message."""
        payload = message_to_dict(message)
        insert = (
            f"INSERT INTO {self.table_name} (session_id, message) "
            f"VALUES (%s, %s)"
        )
        with psycopg.connect(self.connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(insert, (self.session_id, json.dumps(payload)))
            conn.commit()

    def clear(self) -> None:
        """Delete all messages for the current session."""
        delete = f"DELETE FROM {self.table_name} WHERE session_id = %s"
        with psycopg.connect(self.connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(delete, (self.session_id,))
            conn.commit()
