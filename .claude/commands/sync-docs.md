Synchronize documentation with the current codebase.

Check for staleness in these areas:

1. **API endpoints** — Read `server/chronoq_server/api/tasks.py` and `api/metrics.py`. Compare the actual routes, request/response models, and query params against `docs/api-reference.md` and `README.md` API table. Flag any mismatches.

2. **Configuration** — Read `server/chronoq_server/config.py` and `predictor/chronoq_predictor/config.py`. Compare actual env vars and config fields against `docs/configuration.md` and `.env.example`. Flag any mismatches.

3. **Postman collection** — Read `docs/postman/chronoq.postman_collection.json`. Compare endpoints against actual API routes. Flag missing or outdated endpoints.

4. **Test counts** — Run `uv run pytest --co -q` to count tests. Update any references to test counts in CLAUDE.md files if they've changed.

5. **README demo output** — Check if the demo.py wave structure matches what's described in README.md.

For each area: report whether it's in sync or needs updating. If updating is needed, make the changes.
