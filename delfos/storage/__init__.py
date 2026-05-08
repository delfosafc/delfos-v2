"""Persistência: paths, tabelas de resultado e logs em arquivo."""

from delfos.storage.logs import LogWriter
from delfos.storage.paths import Paths
from delfos.storage.results import ResultsStore

__all__ = ["LogWriter", "Paths", "ResultsStore"]
