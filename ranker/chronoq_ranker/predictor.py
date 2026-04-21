"""Deprecated module. Use :mod:`chronoq_ranker.ranker` instead.

Re-exports :class:`~chronoq_ranker.ranker.TaskRanker` under the legacy v1
name so imports like ``from chronoq_ranker.predictor import TaskPredictor``
keep working for one release cycle. A ``DeprecationWarning`` is emitted on
module import.
"""

import warnings

from chronoq_ranker.ranker import TaskRanker as _TaskRanker

warnings.warn(
    "chronoq_ranker.predictor is deprecated; use chronoq_ranker.ranker.",
    DeprecationWarning,
    stacklevel=2,
)

# Alias so ``from chronoq_ranker.predictor import TaskPredictor`` keeps working.
TaskPredictor = _TaskRanker  # noqa: F821  (legacy alias)

__all__ = ["TaskPredictor"]
