from typing import Any, Literal


def build_n8n_test_mock_response(
    *,
    payload: dict[str, Any],
) -> Literal[202]:
    """Return a deterministic mock dispatcher response.

    C11B closes the historical external webhook path. This function never opens
    sockets, follows URLs, or performs HTTP IO.
    """
    del payload
    return 202
