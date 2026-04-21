"""Regression tests for v1 → v2 deprecation shims.

Verifies that legacy imports used by external v1 callers still resolve
to the renamed v2 classes AND emit a ``DeprecationWarning``. When the
aliases are eventually removed (next major version), these tests fail
loudly and the deletion PR must be reviewed carefully.
"""

import warnings


def test_top_level_task_predictor_alias_still_resolves() -> None:
    """`from chronoq_ranker import TaskPredictor` must return the v2 TaskRanker class."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        from chronoq_ranker import TaskPredictor, TaskRanker

        assert TaskPredictor is TaskRanker
        assert any(
            issubclass(w.category, DeprecationWarning) and "TaskPredictor" in str(w.message)
            for w in captured
        ), "DeprecationWarning must fire for top-level TaskPredictor alias"


def test_top_level_predictor_config_alias_still_resolves() -> None:
    """`from chronoq_ranker import PredictorConfig` must return the v2 RankerConfig class."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        from chronoq_ranker import PredictorConfig, RankerConfig

        assert PredictorConfig is RankerConfig
        assert any(
            issubclass(w.category, DeprecationWarning) and "PredictorConfig" in str(w.message)
            for w in captured
        ), "DeprecationWarning must fire for top-level PredictorConfig alias"


def test_predictor_module_shim_is_importable_and_warns() -> None:
    """`from chronoq_ranker.predictor import TaskPredictor` still works + warns on import."""
    import importlib
    import sys

    # Force a fresh import so the module-level warning re-fires.
    sys.modules.pop("chronoq_ranker.predictor", None)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        mod = importlib.import_module("chronoq_ranker.predictor")
        from chronoq_ranker.ranker import TaskRanker

        assert mod.TaskPredictor is TaskRanker
        assert any(
            issubclass(w.category, DeprecationWarning)
            and "chronoq_ranker.predictor" in str(w.message)
            for w in captured
        ), "DeprecationWarning must fire on import of chronoq_ranker.predictor"


def test_config_module_predictor_config_alias_does_not_warn() -> None:
    """`from chronoq_ranker.config import PredictorConfig` resolves silently (no warning).

    Module-level class alias in ``config.py`` is for backward compatibility
    without spam; the noisy deprecation path is via the top-level
    ``chronoq_ranker.__getattr__`` shim.
    """
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        from chronoq_ranker.config import PredictorConfig, RankerConfig

        assert PredictorConfig is RankerConfig
        # No DeprecationWarning expected from this import path.
        assert not any(issubclass(w.category, DeprecationWarning) for w in captured)
