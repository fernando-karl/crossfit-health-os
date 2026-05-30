"""
Database helper functions
Error handling and common query patterns
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
    # Check if response has error attribute (PostgrestResponse)
    if hasattr(response, 'error') and response.error:
        logger.error(f"Supabase error: {response.error}")
        raise HTTPException(
            status_code=500,
            detail=f"{error_message}: {response.error.message if hasattr(response.error, 'message') else str(response.error)}"
        )

    return response.data


def handle_supabase_single(response, not_found_message: str = "Resource not found"):
    """
    Handle Supabase single() queries with error checking

    Args:
        response: Supabase query response
        not_found_message: Message when resource not found

    Returns:
        Single record data

    Raises:
        HTTPException for errors or not found
    """
    data = handle_supabase_response(response, "Failed to fetch resource")

    if not data:
        raise HTTPException(status_code=404, detail=not_found_message)

    return data
