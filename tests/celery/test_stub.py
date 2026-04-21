"""Stub — confirms chronoq-celery is importable. Real tests land in Chunk 3."""

import chronoq_celery


def test_package_importable() -> None:
    assert chronoq_celery.__version__ == "0.2.0"
