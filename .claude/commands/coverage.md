Run tests with coverage and identify untested code.

```bash
uv run pytest --cov=chronoq_ranker --cov=chronoq_demo_server --cov-report=term-missing --tb=short -q
```

After running:
1. Report overall coverage percentage for each package
2. List the top 5 files with lowest coverage
3. For each low-coverage file, identify the specific uncovered lines/functions
4. Suggest which missing tests would have the highest impact
