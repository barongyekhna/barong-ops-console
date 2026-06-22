from collections.abc import Mapping
from typing import Any, Literal


def build_n8n_test_mock_response(
    *,
    payload: dict[str, Any],
    injected_headers: Mapping[str, str] | None = None,
) -> Literal[202]:
    """Return a deterministic mock dispatcher response.

    C11B closes the historical external webhook path. This function never opens
    sockets, follows URLs, or performs HTTP IO.
    """
    del payload
    del injected_headers
    return 202
