"""The job runner: one job at a time, cancellable, and honest about overruns."""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ocengine.fatal import EngineError  # noqa: E402

from blackdream.core.job_runner import (  # noqa: E402
    ABANDONED, CANCELLED, DONE, FAILED, Job, JobAbandoned, JobRunner, Outcome,
    UnexpectedEngineFailure)
from blackdream.core.pipeline import Cancelled, CancelToken  # noqa: E402


def collect():
    outcomes = []
    return outcomes, JobRunner(on_outcome=outcomes.append)


def wait_for(outcomes, count=1, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(outcomes) < count:
        time.sleep(0.005)
    return len(outcomes) >= count


def test_run_now_returns_the_value_and_elapsed_time():
    outcome = JobRunner().run_now(Job("add", lambda token: 1 + 1))
    assert (outcome.status, outcome.value, outcome.ok) == (DONE, 2, True)
    assert outcome.elapsed >= 0.0


def test_an_engine_error_is_carried_through_untouched():
    error = EngineError(detail="the disk is full")
    outcome = JobRunner().run_now(Job("emit", lambda token: (_ for _ in ()).throw(error)))
    assert outcome.status == FAILED
    assert outcome.error is error
    assert outcome.error.detail == "the disk is full"


def test_an_unexpected_exception_keeps_its_type_in_the_detail():
    def boom(token):
        raise IndexError("list index out of range")

    outcome = JobRunner().run_now(Job("boom", boom))
    assert outcome.status == FAILED
    assert isinstance(outcome.error, UnexpectedEngineFailure)
    assert outcome.error.code == "engine.unexpected"
    assert outcome.error.detail == "IndexError: list index out of range"


def test_cancellation_is_cooperative_and_reports_cancelled():
    outcomes, runner = collect()
    inside = threading.Event()

    def body(token):
        inside.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            token.check()
            time.sleep(0.01)
        return "unreachable"

    assert runner.start(Job("long", body, timeout=None)) is True
    assert inside.wait(5)
    assert runner.busy is True
    runner.cancel()
    assert wait_for(outcomes)
    assert outcomes[0].status == CANCELLED
    assert outcomes[0].error is None


def test_a_job_is_refused_while_another_holds_the_engine_objects():
    outcomes, runner = collect()
    release = threading.Event()

    def body(token):
        release.wait(5)
        return "done"

    assert runner.start(Job("first", body)) is True
    assert runner.busy is True
    assert runner.start(Job("second", lambda token: None)) is False
    release.set()
    assert wait_for(outcomes)
    assert [o.job for o in outcomes] == ["first"]


def test_outcome_is_delivered_exactly_once_even_when_the_watchdog_fires():
    outcomes, runner = collect()

    def ignores_cancellation(token):
        time.sleep(0.2)
        return "late"

    runner.start(Job("quick", ignores_cancellation, timeout=0.01))
    assert wait_for(outcomes, timeout=5)
    time.sleep(0.4)
    assert len(outcomes) == 1, "both the worker and the watchdog delivered"


def test_a_thread_that_never_unwinds_is_abandoned_not_killed():
    outcomes, runner = collect()
    hold = threading.Event()

    def blocked_forever(token):
        # Stands in for a syscall that will not return: cancellation cannot reach it.
        hold.wait(30)
        return "never"

    runner.grace = 0.05
    runner.start(Job("blocked", blocked_forever, timeout=0.05))
    assert wait_for(outcomes, timeout=5)
    outcome = outcomes[0]
    assert outcome.status == ABANDONED
    assert isinstance(outcome.error, JobAbandoned)
    assert "0.05 s budget" in outcome.error.detail
    assert "blocked" in outcome.error.detail
    assert runner.busy is True, "the abandoned thread is still alive, as documented"
    assert runner.start(Job("next", lambda token: None)) is False
    hold.set()


def test_a_job_that_honours_cancellation_before_the_grace_ends_is_cancelled():
    outcomes, runner = collect()

    def polite(token):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            token.check()
            time.sleep(0.01)
        return "unreachable"

    runner.grace = 2.0
    runner.start(Job("polite", polite, timeout=0.05))
    assert wait_for(outcomes, timeout=5)
    assert len(outcomes) == 1
    assert outcomes[0].status in (CANCELLED, ABANDONED)


def test_cancel_without_a_running_job_does_nothing_harmful():
    runner = JobRunner()
    assert runner.cancel() is False
    assert runner.busy is False


def test_run_now_does_not_block_future_starts():
    outcomes, runner = collect()
    runner.run_now(Job("sync", lambda token: 7))
    assert outcomes == [], "run_now returns the outcome, it does not broadcast it"
    assert runner.start(Job("async", lambda token: 8)) is True
    assert wait_for(outcomes)


def test_cancelled_is_what_a_token_raises_for_a_headless_host():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        token.check()
    assert token.cancelled is True


def test_outcome_ok_is_only_true_for_a_finished_job():
    assert Outcome(job="a", status=DONE).ok is True
    for status in (FAILED, CANCELLED, ABANDONED):
        assert Outcome(job="a", status=status).ok is False
