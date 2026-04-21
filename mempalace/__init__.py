"""MemCitadel — enterprise-scale RAG on Elasticsearch."""

import logging

from .version import __version__

# Suppress noisy Elasticsearch client warnings
logging.getLogger("elastic_transport").setLevel(logging.WARNING)

__all__ = ["__version__"]
