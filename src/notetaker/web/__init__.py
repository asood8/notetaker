"""The optional local web front end. Install with `pip install notetaker[web]`."""

__all__ = ["create_app"]


def create_app():
    """Import lazily so the CLI works without the web extras installed."""
    from notetaker.web.app import create_app as build

    return build()
