"""Root entrypoint shim for Prefect Horizon / FastMCP Cloud (`server.py:mcp`)."""

from superpower_wiki_mcp.server import app, main, mcp

__all__ = ["mcp", "app", "main"]

if __name__ == "__main__":
    main()
