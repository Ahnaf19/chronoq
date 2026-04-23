"""Regression tests for the auto-retrain trigger under low-resolution system clocks.

Windows ``datetime.now()`` is backed by ``GetSystemTimeAsFileTime`` with roughly
15.6ms resolution, so rapid consecutive calls can return the same ``datetime``.
If the auto-retrain decision is driven solely by ``store.count_since(after)`` with
strict ``>`` comparison, records written inside the same clock tick as
``_last_retrain_at`` are missed and the retrain never fires again on that tick.

These tests simulate the failure mode in a platform-independent way by pinning
``datetime.now`` to a fixed instant.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from chronoq_ranker import RankerConfig, TaskRanker
from chronoq_ranker.storage.memory import MemoryStore


@pytest.fixture()
def low_threshold_config() -> RankerConfig:
    return RankerConfig(
        cold_start_threshold=10,
        retrain_every_n=5,
        min_groups=2,
        allow_degrade=True,
    )


def test_auto_retrain_fires_when_clock_is_frozen(
    low_threshold_config: RankerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a low-resolution clock: all ``datetime.now(UTC)`` calls return the same value.

    On Windows, rapid ``record()`` calls after a retrain can all carry the same
    ``recorded_at`` as ``_last_retrain_at``. Strict ``>`` in ``count_since`` then
    returns 0 and auto-retrain silently stops firing.

    After the fix, the in-memory monotonic counter triggers retrain regardless of
    the wall-clock timestamp precision.
    """
    frozen_instant = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)

    # Patch ``datetime`` in the two modules that stamp timestamps.
    import chronoq_ranker.ranker as ranker_mod
    import chronoq_ranker.schemas as schemas_mod

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return frozen_instant

    monkeypatch.setattr(ranker_mod, "datetime", FrozenDatetime)
    monkeypatch.setattr(schemas_mod, "datetime", FrozenDatetime)

    store = MemoryStore()
    ranker = TaskRanker(config=low_threshold_config, storage=store)

    retrain_calls: list[object] = []
    original_retrain = ranker.retrain

    def counting_retrain() -> object:
        result = original_retrain()
        retrain_calls.append(result)
        return result

    ranker.retrain = counting_retrain  # type: ignore[method-assign]

    # First batch — crosses retrain_every_n=5.
    for i in range(6):
        ranker.record(task_type="resize", payload_size=100 + i, actual_ms=float(100 + i * 10))

    first_count = len(retrain_calls)
    assert first_count >= 1, (
        f"Auto-retrain must fire at least once after crossing the threshold, got {first_count}."
    )

    # Second batch — under a frozen clock, all ``recorded_at`` == ``_last_retrain_at``.
    # With the old datetime-strict-> check, ``count_since`` returns 0 forever.
    for i in range(6):
        ranker.record(task_type="resize", payload_size=200 + i, actual_ms=float(200 + i * 10))

    second_count = len(retrain_calls)
    assert second_count > first_count, (
        "Auto-retrain must fire again on the second threshold crossing even when "
        "the system clock does not advance between record() and retrain() (Windows "
        f"~15ms tick). Fired {first_count} times after first batch, {second_count} "
        "after second."
    )


def test_records_written_in_same_tick_as_retrain_count_toward_next_retrain(
    low_threshold_config: RankerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Records stamped identical to ``_last_retrain_at`` must still push toward the next retrain.

    Direct unit-ish coverage of the monotonic counter: we freeze the clock and
    check that ``retrain_every_n`` consecutive records fire exactly one retrain.
    """
    frozen_instant = datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC)

    import chronoq_ranker.ranker as ranker_mod
    import chronoq_ranker.schemas as schemas_mod

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return frozen_instant

    monkeypatch.setattr(ranker_mod, "datetime", FrozenDatetime)
    monkeypatch.setattr(schemas_mod, "datetime", FrozenDatetime)

    ranker = TaskRanker(config=low_threshold_config, storage=MemoryStore())

    retrain_calls: list[object] = []
    original_retrain = ranker.retrain

    def counting_retrain() -> object:
        result = original_retrain()
        retrain_calls.append(result)
        return result

    ranker.retrain = counting_retrain  # type: ignore[method-assign]

    # Exactly retrain_every_n records -> exactly one retrain.
    for i in range(low_threshold_config.retrain_every_n):
        ranker.record(task_type="resize", payload_size=i, actual_ms=float(10 + i))
    assert len(retrain_calls) == 1

    # Another full batch -> exactly one more retrain (cumulative two).
    for i in range(low_threshold_config.retrain_every_n):
        ranker.record(task_type="resize", payload_size=100 + i, actual_ms=float(50 + i))
    assert len(retrain_calls) == 2
