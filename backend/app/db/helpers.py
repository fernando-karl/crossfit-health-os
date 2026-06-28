"""
DEPRECATED — Supabase helper functions (legacy).

Production code uses SQLAlchemy via ``app.db.session``. These helpers remain
only for backward compatibility with old tests; do not use in new code.
"""
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


def handle_supabase_response(response, error_message: str = "Database error"):
    """
    Validate Supabase response and handle errors

    Args:
        response: Supabase query response
        error_message: Custom error message

    Returns:
        response.data if successful

    Raises:
        HTTPException if error occurred
    """
    if hasattr(response, 'error') and response.error:
        logger.error(f"Supabase error: {response.error}")
        raise HTTPException(
            status_code=500,
            detail=f"{error_message}: {response.error.message if hasattr(response.error, 'message') else str(response.error)}"
        )

    if hasattr(response, 'data'):
        return response.data

    return response


def handle_supabase_single(response, not_found_message: str = "Resource not found"):
    """
    Handle Supabase single-row response

    Returns:
        Single row dict

    Raises:
        HTTPException if not found or error
    """
    data = handle_supabase_response(response, "Failed to fetch resource")

    if not data:
        raise HTTPException(status_code=404, detail=not_found_message)

    return data[0] if isinstance(data, list) else data
