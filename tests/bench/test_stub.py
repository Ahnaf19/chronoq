"""Stub — confirms chronoq-bench is importable. Real tests land in Chunk 2."""

import chronoq_bench


def test_package_importable() -> None:
    assert chronoq_bench.__version__ == "0.2.0"
