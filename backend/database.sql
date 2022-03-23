-- 4CAT Database structure
-- Running this file as an SQL query should be enough to set up the database
-- on a fresh 4CAT install - individual data sources may also provide their
-- own database.sql files with data source-specific tables and indices.

-- 4CAT settings table
CREATE TABLE IF NOT EXISTS fourcat_settings (
  name                   TEXT UNIQUE PRIMARY KEY,
  value                  TEXT DEFAULT '{}'
);

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
  id                SERIAL PRIMARY KEY,
  key               text,
  type              text DEFAULT 'search',
  key_parent        text DEFAULT '',
  owner             VARCHAR DEFAULT 'anonymous',
  query             text,
  job               integer DEFAULT 0,
  parameters        text,
  result_file       text DEFAULT '',
  timestamp         integer,
  status            text,
  num_rows          integer DEFAULT 0,
  is_finished       boolean DEFAULT FALSE,
  is_private        boolean DEFAULT TRUE,
  software_version  text,
  software_file     text DEFAULT '',
  annotation_fields text DEFAULT ''
);

-- annotations
CREATE TABLE IF NOT EXISTS annotations (
  key               text UNIQUE PRIMARY KEY,
  annotations       text DEFAULT ''
);

-- metrics
CREATE TABLE IF NOT EXISTS metrics (
  metric             text,
  datasource         text,
  board              text,
  date               text,
  count              integer
);

-- users
CREATE TABLE IF NOT EXISTS users (
  name               TEXT UNIQUE PRIMARY KEY,
  password           TEXT,
  is_admin           BOOLEAN DEFAULT FALSE,
  register_token     TEXT DEFAULT '',
  timestamp_token    INTEGER DEFAULT 0,
  timestamp_seen     INTEGER DEFAULT 0,
  userdata           TEXT DEFAULT '{}',
  is_deactivated     BOOLEAN DEFAULT FALSE
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


-- fourcat settings insert default settings
INSERT INTO fourcat_settings
  (name, value)
  Values
    ('DATASOURCES', '{"bitchute": {}, "custom": {}, "douban": {}, "customimport": {}, "parler": {}, "reddit": { "boards": "*", }, "telegram": {}, "twitterv2": {"id_lookup": False} }')
    ('TOOL_NAME', '"4CAT"'),
    ('TOOL_NAME_LONG', '"4CAT: Capture and Analysis Toolkit"'),
    ('PATH_VERSION', '".git-checked-out"'),
    ('GITHUB_URL', '"https://github.com/digitalmethodsinitiative/4cat"'),
    ('EXPIRE_DATASETS', '0'),
    ('EXPIRE_ALLOW_OPTOUT', 'true'),
    ('WARN_INTERVAL', '600'),
    ('WARN_LEVEL', '"WARNING"'),
    ('WARN_SLACK_URL', 'null'),
    ('WARN_EMAILS', 'null'),
    ('ADMIN_EMAILS', 'null'),
    ('MAILHOST', 'null'),
    ('MAIL_SSL', 'false'),
    ('MAIL_USERNAME', 'null'),
    ('MAIL_PASSWORD', 'null'),
    ('NOREPLY_EMAIL', '"noreply@localhost"'),
    ('SCRAPE_TIMEOUT', '5'),
    ('SCRAPE_PROXIES', '{"http": []}'),
    ('IMAGE_INTERVAL', '3600'),
    ('MAX_EXPLORER_POSTS', '100000'),
    ('FLASK_APP', '"webtool/fourcat"'),
    ('SERVER_HTTPS', 'false'),
    ('SERVER_NAME', '"localhost"'),
    ('HOSTNAME_WHITELIST_NAME', '"Automatic login"'),
    ('HOSTNAME_WHITELIST', '["localhost"]'),
    ('HOSTNAME_WHITELIST_API', '["localhost"]')
    ON CONFLICT DO NOTHING;
