"""
Shared dependency module.
Centralizes the database instance, user identity lookup, and other objects reused by routes.
"""

from fastapi import Request

from db import Database

# Global database instance connected and closed by the server.py lifecycle.
db = Database()


def get_uid(request: Request):
    """
    Return the current user's UID.
    Local development defaults to uid=1 when no authenticated session is available.
    """
    return getattr(request.state, "uid", 1)
