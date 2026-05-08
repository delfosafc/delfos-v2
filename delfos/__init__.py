"""delfos — controle do equipamento Delfos (Central + UASGs) via porta serial.

A API pública estável vive aqui. Submódulos como ``delfos.protocol`` são
acessíveis mas considerados internos até serem promovidos a este __init__.
"""

from delfos.events import (
    ErrorEvent,
    Event,
    EventBus,
    JobAborted,
    JobFinished,
    JobStarted,
    MeasurementSample,
    NullBus,
    Progress,
    StepCompleted,
    StepStarted,
    UnitResponse,
)
from delfos.jobs import Job, JobResult, Step, load_job
from delfos.session import Session

__version__ = "0.1.0"

__all__ = [
    # API principal
    "Session",
    "load_job",
    # Schema
    "Job",
    "JobResult",
    "Step",
    # Bus
    "EventBus",
    "NullBus",
    "Event",
    # Eventos
    "JobStarted",
    "StepStarted",
    "StepCompleted",
    "Progress",
    "UnitResponse",
    "MeasurementSample",
    "JobAborted",
    "JobFinished",
    "ErrorEvent",
]
