"""
Regenerate tests/schema_baseline.json from the current backend/database.sql.

This script should not be needed--a migrate script and database.sql should be 
maintained in tandem so that the tests pass without needing to update the baseline.

But we do need A baseline for earliest columns.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.test_schema_consistency import _parse_database_sql  # noqa: E402

baseline_path = Path(__file__).parent / "schema_baseline.json"
tables = _parse_database_sql()

# Convert frozensets to sorted lists for stable, readable diffs.
output = {table: sorted(cols) for table, cols in sorted(tables.items())}
baseline_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

print(f"Baseline written to {baseline_path}")
for table, cols in output.items():
	print(f"  {table}: {len(cols)} column(s)")
