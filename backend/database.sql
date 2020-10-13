-- 4CAT Database structure
-- Running this file as an SQL query should be enough to set up the database
-- on a fresh 4CAT install - individual data sources may also provide their
-- own database.sql files with data source-specific tables and indices.

-- jobs table
CREATE TABLE IF NOT EXISTS jobs (
  id                     SERIAL PRIMARY KEY,
  jobtype                text    DEFAULT 'misc',
  remote_id              text,
  details                text,
  timestamp              integer,
  timestamp_after        integer DEFAULT 0,
  timestamp_lastclaimed  integer DEFAULT 0,
  timestamp_claimed      integer DEFAULT 0,
  status                 text,
  attempts               integer DEFAULT 0,
  interval               integer DEFAULT 0
);

-- enforce
CREATE UNIQUE INDEX IF NOT EXISTS unique_job
  ON jobs (
    jobtype,
    remote_id
  );


-- queries
CREATE TABLE IF NOT EXISTS datasets (
  id               SERIAL PRIMARY KEY,
  key              text,
  type             text DEFAULT 'search',
  key_parent       text DEFAULT '',
  query            text,
  job              integer DEFAULT 0,
  parameters       text,
  result_file      text DEFAULT '',
  timestamp        integer,
  status           text,
  num_rows         integer DEFAULT 0,
  is_finished      boolean DEFAULT FALSE,
  software_version text,
  software_file    text DEFAULT ''
);

-- users
CREATE TABLE IF NOT EXISTS users (
  name               TEXT UNIQUE PRIMARY KEY,
  password           TEXT,
  is_admin           BOOLEAN DEFAULT FALSE,
  register_token     TEXT DEFAULT '',
  timestamp_token    INTEGER DEFAULT 0,
  timestamp_seen     INTEGER DEFAULT 0,
  userdata           TEXT DEFAULT '{}'
);

INSERT INTO users
  (name, password)
  VALUES ('anonymous', ''), ('autologin', '')
  ON CONFLICT DO NOTHING;

-- access tokens
CREATE TABLE IF NOT EXISTS access_tokens (
  name TEXT UNIQUE PRIMARY KEY,
  token TEXT,
  calls INTEGER DEFAULT 0,
  expires INTEGER DEFAULT 0
);


-- favourites
CREATE TABLE IF NOT EXISTS users_favourites (
  name TEXT,
  key TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_favourite
  ON users_favourites (
    name,
    key
  );

-- used to quickly update table counts
CREATE FUNCTION count_estimate(query text) RETURNS bigint AS $$
  DECLARE
    rec record;
  BEGIN
    EXECUTE 'EXPLAIN (FORMAT json) ' || query INTO rec;
    RETURN rec."QUERY PLAN"->0->'Plan'->'Plan Rows';
  END;
  $$ LANGUAGE plpgsql VOLATILE STRICT;
