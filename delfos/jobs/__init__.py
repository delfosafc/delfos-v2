"""Jobs — descrição declarativa + execução de uma sequência de medidas.

Schema em ``schema.py`` (Step + Job), carregamento em ``loader.py``,
execução em ``runner.py`` (``JobRunner``).
"""

from delfos.jobs.loader import KNOWN_TASKS, REMOVED_TASKS, load_job
from delfos.jobs.runner import JobResult, JobRunner
from delfos.jobs.schema import Job, Step

__all__ = [
    "KNOWN_TASKS",
    "REMOVED_TASKS",
    "Job",
    "JobResult",
    "JobRunner",
    "Step",
    "load_job",
]
