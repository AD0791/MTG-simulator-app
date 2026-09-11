"""OpenAPI response declarations shared by every v1 router.

Declaring a 422 replaces the `HTTPValidationError` entry FastAPI would generate,
which no longer describes what the API returns: every rejection — a malformed
request or an impossible plan — is a `Problem`.
"""

from typing import Any

from fastapi import status

from ...schemas import Problem

Responses = dict[int | str, dict[str, Any]]

NOT_FOUND: Responses = {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such live run"}
}
INVALID_REQUEST: Responses = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The request is malformed, or the plan it describes is not valid",
    }
}
