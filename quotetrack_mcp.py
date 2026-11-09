"""Punto de entrada del servidor MCP de QuoteTrack (se empaqueta como QuoteTrackMCP.exe)."""
import sys

from app.mcp_servidor import main

if __name__ == "__main__":
    sys.exit(main())
