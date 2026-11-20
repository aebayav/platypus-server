"""Platypus server setup TUI package."""

try:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("platypus-server")
    except PackageNotFoundError:
        __version__ = "unknown"
except ImportError:  # pragma: no cover
    __version__ = "unknown"
