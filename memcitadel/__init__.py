"""MemPalace — Give your AI a memory. No API key required."""

import logging

from .cli import main  # noqa: E402
from .version import __version__  # noqa: E402

# Suppress noisy Elasticsearch client warnings
logging.getLogger("elastic_transport").setLevel(logging.WARNING)

__all__ = ["main", "__version__"]
