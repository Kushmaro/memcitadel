"""MemCitadel — enterprise-scale RAG on Elasticsearch."""

import logging
import os
import sys


def _strip_leaked_pythonpath_from_sys_path() -> None:
    # Venvs inherit PYTHONPATH; on multi-Python systems it can cause
    # transitive imports to load compiled extensions (pydantic_core,
    # chromadb_rust_bindings) from the wrong ABI. Remove sys.path entries
    # the interpreter populated from PYTHONPATH so this process imports
    # only the venv's own packages. Comparison normalizes case + separators
    # so Windows paths and trailing-separator quirks do not slip through
    # string equality. The empty-string CWD marker on sys.path is preserved
    # regardless, so PYTHONPATH=. does not collapse the implicit current
    # directory.
    #
    # os.environ is intentionally NOT modified here. CLI entry points
    # (mempalace.cli:main, mempalace.mcp_server:main) drop PYTHONPATH from
    # the env themselves so any subprocess they spawn starts clean. Host
    # applications that embed mempalace as a library (e.g. import
    # mempalace.searcher) keep their PYTHONPATH intact for their own
    # unrelated subprocesses.
    leaked = os.environ.get("PYTHONPATH", None)
    if not leaked:
        return

    def _norm(path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    leaked_entries = {_norm(p) for p in leaked.split(os.pathsep) if p}
    sys.path[:] = [p for p in sys.path if not p or _norm(p) not in leaked_entries]


_strip_leaked_pythonpath_from_sys_path()

from .version import __version__  # noqa: E402

# Suppress noisy Elasticsearch client warnings
logging.getLogger("elastic_transport").setLevel(logging.WARNING)

__all__ = ["__version__"]
