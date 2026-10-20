"""JobQueue with the fake provider: run, fail, retry, stop, pause."""

from __future__ import annotations

import threading
import time

from src.gen.fake_provider import FakeProvider
from src.gen.models import Job, JobStatus
from src.gen.output import save_outputs
from src.gen.queue import JobQueue, QueueSettings


def make_queue(tmp_path, step=0.0, steps=4, **kw):
    finished = threading.Event()
    updates = []
    q = JobQueue(
        FakeProvider(step_seconds=step, steps=steps),
        saver=lambda job, files: save_outputs(job, files, tmp_path),
        on_update=lambda job: updates.append((job.id, job.status)),
        on_finished=finished.set,
    )
    return q, finished, updates


def jobs_for(*prompts):
    return [Job(p, index=i) for i, p in enumerate(prompts, 1)]


def test_batch_runs_to_done(tmp_path):
    q, finished, updates = make_queue(tmp_path)
    jobs = jobs_for("a cat", "a dog", "a fox", "an owl", "a bee")
    assert q.start(jobs, {"count": 2}, QueueSettings(threads=3)) == 5
    assert q.wait(10) and finished.wait(2)
    assert all(j.status is JobStatus.DONE for j in jobs)
    assert all(len(j.outputs) == 2 and j.outputs[0].exists() for j in jobs)
    assert q.stats()["done"] == 5 and q.stats()["total"] == 5
    assert any(s is JobStatus.RUNNING for _, s in updates)


def test_fail_and_flaky_retry(tmp_path):
    q, finished, _ = make_queue(tmp_path)
    jobs = jobs_for("ok", "bad [fail]", "shaky [flaky]")
    q.start(jobs, {}, QueueSettings(threads=1, max_retries=1))
    assert q.wait(10)
    assert [j.status for j in jobs] == [JobStatus.DONE, JobStatus.FAILED, JobStatus.DONE]
    assert jobs[1].error and jobs[2].attempts == 2

    # Manual retry of the failed row runs it again (and it fails again).
    assert q.retry(jobs) == 1
    assert q.wait(10)
    assert jobs[1].status is JobStatus.FAILED and jobs[1].attempts == 1


def test_flaky_without_retries_fails(tmp_path):
    q, _, _ = make_queue(tmp_path)
    jobs = jobs_for("x [flaky]")
    q.start(jobs, {}, QueueSettings(threads=1, max_retries=0))
    assert q.wait(10)
    assert jobs[0].status is JobStatus.FAILED


def test_stop_marks_running_and_queued(tmp_path):
    q, finished, _ = make_queue(tmp_path, step=0.05, steps=20)
    jobs = jobs_for(*[f"p{i}" for i in range(6)])
    q.start(jobs, {}, QueueSettings(threads=2))
    time.sleep(0.2)
    q.stop()
    assert q.wait(5) and finished.wait(2)
    assert all(j.status is JobStatus.STOPPED for j in jobs)
    # Stopped jobs can be retried to completion.
    q.provider.step_seconds = 0
    assert q.retry(jobs) == 6
    assert q.wait(10)
    assert all(j.status is JobStatus.DONE for j in jobs)


def test_pause_holds_new_jobs(tmp_path):
    q, _, _ = make_queue(tmp_path, step=0.02, steps=5)
    jobs = jobs_for("a", "b", "c")
    q.pause()
    q.start(jobs, {}, QueueSettings(threads=1))
    time.sleep(0.3)
    assert all(j.status is JobStatus.QUEUED for j in jobs)
    q.resume()
    assert q.wait(10)
    assert all(j.status is JobStatus.DONE for j in jobs)


def test_delay_between_jobs(tmp_path):
    q, _, _ = make_queue(tmp_path)
    jobs = jobs_for("a", "b", "c")
    t0 = time.monotonic()
    q.start(jobs, {}, QueueSettings(threads=1, delay_min=0.15, delay_max=0.15))
    assert q.wait(10)
    assert time.monotonic() - t0 >= 0.3  # two delays (none before the first job)
