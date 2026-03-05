# Database Migrations

Chronoq uses [Alembic](https://alembic.sqlalchemy.org/) for SQLite schema versioning.

## Setup

Alembic is an optional dependency for production deployments. The predictor's `SqliteStore` uses `CREATE TABLE IF NOT EXISTS` for automatic table creation, so migrations are only needed for schema evolution on existing databases.

```bash
pip install alembic sqlalchemy
```

## Usage

```bash
# Apply all pending migrations
alembic -c migrations/alembic.ini upgrade head

# Check current revision
alembic -c migrations/alembic.ini current

# Create a new migration
alembic -c migrations/alembic.ini revision -m "description of change"

# Downgrade one step
alembic -c migrations/alembic.ini downgrade -1
```

## Migration History

| Revision | Description |
|----------|-------------|
| 001 | Initial telemetry table creation |
| 002 | Add indexes on task_type and model_version_at_record |

## Custom Database Path

Set the `CHRONOQ_PREDICTOR_STORAGE` environment variable:

```bash
CHRONOQ_PREDICTOR_STORAGE=sqlite:///custom_path.db alembic -c migrations/alembic.ini upgrade head
```
