"""Testes do delfos.events."""

from __future__ import annotations

from delfos.events import (
    EventBus,
    JobFinished,
    JobStarted,
    NullBus,
    Progress,
    StepCompleted,
    StepStarted,
    UnitResponse,
)


def test_subscribe_and_publish():
    bus = EventBus()
    received: list = []
    bus.subscribe(received.append)
    event = JobStarted(job_name="x", n_steps=3)
    bus.publish(event)
    assert received == [event]


def test_multiple_subscribers_all_get_the_event():
    bus = EventBus()
    a, b = [], []
    bus.subscribe(a.append)
    bus.subscribe(b.append)
    event = StepStarted(step=1, task="ligar")
    bus.publish(event)
    assert a == b == [event]


def test_unsubscribe():
    bus = EventBus()
    received: list = []
    bus.subscribe(received.append)
    bus.unsubscribe(received.append)
    bus.publish(StepCompleted(step=1, task="ligar"))
    assert received == []


def test_unsubscribe_unknown_is_silent():
    bus = EventBus()
    bus.unsubscribe(lambda e: None)  # não raises


def test_subscribers_can_unsubscribe_during_publish():
    """Snapshot de subscribers no momento do publish — quem se desinscreve
    durante o callback não quebra a iteração."""
    bus = EventBus()
    log: list = []

    def first(event):
        log.append("first")
        bus.unsubscribe(second)

    def second(event):
        log.append("second")

    bus.subscribe(first)
    bus.subscribe(second)
    bus.publish(JobFinished(job_name="x", n_steps_completed=0))
    assert "first" in log
    assert "second" in log  # ainda recebe nesta publicação


def test_progress_percent():
    p = Progress(current=3, total=10)
    assert p.percent == 30.0
    p2 = Progress(current=0, total=0)
    assert p2.percent == 0.0


def test_unit_response_default_detail():
    u = UnitResponse(unit_id=5, success=True)
    assert u.detail == ""


def test_null_bus_does_nothing():
    bus = NullBus()
    received: list = []
    bus.subscribe(received.append)
    bus.publish(JobStarted(job_name="x", n_steps=1))
    assert received == []
