"""orinyx-mcp: the Orinyx MCP server, command-line tool and REST client.

A CLIENT of the Orinyx verification API. Nothing here decides a verdict: every tool call is
an ordinary REST request carrying the caller's own credential, and the engine's rules,
citations, scopes, tenancy, rate limits and audit record apply unchanged."""

__version__ = "0.1.5"
