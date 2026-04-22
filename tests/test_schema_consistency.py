"""
Consistency checks between backend/database.sql and helper-scripts/migrate/*.py.

Tests should catch the following cases:

  1. migrate-*.py checks:
     Every column added via ALTER TABLE ADD or dropped via ALTER TABLE DROP in 
	 a migration must be present in database.sql (so fresh installs include it).

  2. database.sql checks:
     Every column present in database.sql (that is not in the grandfathered
     baseline tests/schema_baseline.json) must have a corresponding migration
     that adds or renames it into existence.

Should not need Docker and can be a first-pass PR check.
"""
import json
import re
from pathlib import Path

PATH_ROOT = Path(__file__).parent.parent.resolve()
DATABASE_SQL = PATH_ROOT / "backend" / "database.sql"
MIGRATE_DIR = PATH_ROOT / "helper-scripts" / "migrate"

# Lines whose first keyword marks a table-level constraint, not a column def.
_CONSTRAINT_START = re.compile(
	r"^(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|CONSTRAINT|EXCLUDE)\b",
	re.IGNORECASE,
)


def _parse_database_sql():
	"""Return {table_name: frozenset(column_names)} from CREATE TABLE blocks."""
	sql = DATABASE_SQL.read_text(encoding="utf-8")
	tables = {}
	# Matches the full CREATE TABLE (...); block, including IF NOT EXISTS
	pattern = re.compile(
		r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\)\s*;",
		re.IGNORECASE | re.DOTALL,
	)
	for match in pattern.finditer(sql):
		table = match.group(1).lower()
		columns = set()
		for line in match.group(2).split("\n"):
			line = line.strip().rstrip(",").strip()
			# Skip blank lines and SQL comment lines
			if not line or line.startswith("--"):
				continue
			# Skip table-level constraint lines
			if _CONSTRAINT_START.match(line):
				continue
			# The column name should always be the first identifier on the line
			col_match = re.match(r'"?(\w+)"?', line)
			if col_match:
				columns.add(col_match.group(1).lower())
		tables[table] = frozenset(columns)
	return tables


def _parse_migration_alterations():
	"""
	Scan all migrate-*.py scripts and return:
	  adds    — list of (script_name, table, column) for ADD [COLUMN] statements
	  drops   — list of (script_name, table, column) for DROP [COLUMN] statements
	  renames — dict {(table, old_column): new_column} for RENAME COLUMN statements

	Only tables with static names are captured (skip the dynamic names (e.g. posts_%s) 
	hopefully they won't be needed for much longer)
	"""
	adds, drops = [], []
	renames = {}
	for path in sorted(MIGRATE_DIR.glob("migrate-*.py")):
		text = path.read_text(encoding="utf-8")
		# added
		for m in re.finditer(
			r"ALTER\s+TABLE\s+(\w+)\s+ADD(?:\s+COLUMN)?\s+(\w+)",
			text,
			re.IGNORECASE,
		):
			adds.append((path.name, m.group(1).lower(), m.group(2).lower()))
        # dropped
		for m in re.finditer(
			r"ALTER\s+TABLE\s+(\w+)\s+DROP(?:\s+COLUMN)?(?:\s+IF\s+EXISTS)?\s+(\w+)",
			text,
			re.IGNORECASE,
		):
			drops.append((path.name, m.group(1).lower(), m.group(2).lower()))
        # renamed
		for m in re.finditer(
			r"ALTER\s+TABLE\s+(\w+)\s+RENAME\s+COLUMN\s+(\w+)\s+TO\s+(\w+)",
			text,
			re.IGNORECASE,
		):
			renames[(m.group(1).lower(), m.group(2).lower())] = m.group(3).lower()
	return adds, drops, renames


def _parse_migration_creates():
	"""
	Scan all migrate-*.py scripts for CREATE TABLE statements and return
	{table_name: frozenset(column_names)}.

	Whole-table creations performed by migrations (e.g. the settings table)
	"""
	created = {}
	pattern = re.compile(
		r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\)\s*;",
		re.IGNORECASE | re.DOTALL,
	)
	for path in sorted(MIGRATE_DIR.glob("migrate-*.py")):
		text = path.read_text(encoding="utf-8")
		for match in pattern.finditer(text):
			table = match.group(1).lower()
			columns = set()
			for line in match.group(2).split("\n"):
				line = line.strip().rstrip(",").strip()
				if not line or line.startswith("--"):
					continue
				if _CONSTRAINT_START.match(line):
					continue
				col_match = re.match(r'"?(\w+)"?', line)
				if col_match:
					columns.add(col_match.group(1).lower())
			if table in created:
				created[table] = created[table] | frozenset(columns)
			else:
				created[table] = frozenset(columns)
	return created


def _resolve_renames(table, column, renames):
	"""Follow the rename chain for (table, column) and return the final name."""
	seen = set()
	while (table, column) in renames:
		if (table, column) in seen:
			break  # cycle guard
		seen.add((table, column))
		column = renames[(table, column)]
	return column


def test_migration_adds_present_in_database_sql():
	"""
	Every column added by a migration script must exist in database.sql.

	A column added to existing installs via ALTER TABLE ADD must also be
	declared in database.sql so that fresh installs include it from the start.
	Add the column to database.sql if this test fails.

	Columns that are subsequently renamed by a later migration are checked
	under their final name.
	"""
	tables = _parse_database_sql()
	adds, _, renames = _parse_migration_alterations()

	missing = []
	for script, table, column in adds:
		if table not in tables:
			continue
		final_column = _resolve_renames(table, column, renames)
		if final_column not in tables[table]:
			missing.append(
				f"  {script}: ALTER TABLE {table} ADD ... {column}"
				+ (f" (renamed to {final_column})" if final_column != column else "")
				+ f" — '{final_column}' not found in '{table}' block in database.sql"
			)

	assert not missing, (
		"The following migration ADD columns are missing from backend/database.sql.\n"
		"Add them to the corresponding CREATE TABLE block in database.sql:\n"
		+ "\n".join(missing)
	)


def test_migration_drops_absent_from_database_sql():
	"""
	Every column dropped by a migration script must be absent from database.sql.

	If a column is removed from existing installs via ALTER TABLE DROP, the
	column definition must also be removed from database.sql.
	
	Remove the column from database.sql if this test fails.
	"""
	tables = _parse_database_sql()
	_, drops, _ = _parse_migration_alterations()

	still_present = [
		f"  {script}: ALTER TABLE {table} DROP ... {column}"
		f" — '{column}' still present in '{table}' block in database.sql"
		for script, table, column in drops
		if table in tables and column in tables[table]
	]

	assert not still_present, (
		"The following migration DROP columns are still present in backend/database.sql.\n"
		"Remove them from the corresponding CREATE TABLE block in database.sql:\n"
		+ "\n".join(still_present)
	)


def test_database_sql_columns_have_migrations():
	"""
	Every column in database.sql that is not in the schema baseline must have
	a corresponding migration that adds, renames, or creates it.

	This is the reverse of test_migration_adds_present_in_database_sql: it
	catches the case where someone adds a column to database.sql (so fresh
	installs include it) but forgets to write a migration (so existing installs
	never get it).

	The baseline (tests/schema_baseline.json) grandfathers in all columns that
	existed when this check was introduced.  New columns added after the
	baseline was generated must be covered by a migration; if they are, this
	test passes automatically without any baseline update.
    
	See: tests/update_schema_baseline.py
	"""
	baseline_path = Path(__file__).parent / "schema_baseline.json"
	if not baseline_path.exists():
		# fail and notify that we are unable to verify new columns without a baseline
		assert False, (
            f"Baseline file {baseline_path} not found. Cannot verify new columns in "
            "backend/database.sql without a baseline of pre-migration columns.\n"
            "Generate the baseline from the current database.sql:\n"
            "    python tests/update_schema_baseline.py\n"
        )
	else:
		baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

	tables = _parse_database_sql()
	adds, _, renames = _parse_migration_alterations()
	created_by_migrations = _parse_migration_creates()

	# Build the set of (table, column) pairs fully accounted for by migrations.
	migration_columns: set[tuple[str, str]] = set()
	# ADD statements: follow any subsequent rename to the final column name.
	for _, table, column in adds:
		final = _resolve_renames(table, column, renames)
		migration_columns.add((table, final))
	# RENAME targets: the destination name is introduced by the migration.
	for (table, _), new_col in renames.items():
		migration_columns.add((table, new_col))
	# Whole-table CREATE TABLE statements in migration scripts.
	for table, columns in created_by_migrations.items():
		for col in columns:
			migration_columns.add((table, col))

	unaccounted = []
	for table, columns in tables.items():
		baseline_cols = set(baseline.get(table, []))
		for col in sorted(columns):
			if col in baseline_cols:
				continue  # grandfathered column, pre-dates this check
			if (table, col) in migration_columns:
				continue  # covered by a migration script
			unaccounted.append(f"  {table}.{col}")

	assert not unaccounted, (
		"The following columns in backend/database.sql have no corresponding migration "
		"and are not in the schema baseline.\n"
		"Write a migration in helper-scripts/migrate/ so existing installs also "
		"receive this column.\n"
		"If this column genuinely predates the migration system, regenerate the "
		"baseline instead:\n"
		"    python tests/update_schema_baseline.py\n"
		+ "\n".join(sorted(unaccounted))
	)
