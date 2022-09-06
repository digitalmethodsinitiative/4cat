-- 4CAT Database structure
-- Running this file as an SQL query should be enough to set up the database
-- on a fresh 4CAT install - individual data sources may also provide their
-- own database.sql files with data source-specific tables and indices.

-- 4CAT settings table
CREATE TABLE IF NOT EXISTS settings (
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
  progress          float DEFAULT 0.0,
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

-- notifications
CREATE TABLE IF NOT EXISTS users_notifications (
    id                  SERIAL PRIMARY KEY,
    username            TEXT,
    notification        TEXT,
    timestamp_expires   INTEGER,
    allow_dismiss       BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS users_notifications_name
  ON users_notifications (
    username
  );

CREATE UNIQUE INDEX IF NOT EXISTS users_notifications_unique
  ON users_notifications (
    username, notification
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
INSERT INTO settings
  (name, value)
  Values
    ('DATASOURCES', '{"bitchute": {}, "custom": {}, "douban": {}, "customimport": {}, "parler": {}, "reddit": {"boards": "*"}, "telegram": {}, "twitterv2": {"id_lookup": false}}'),
    ('4cat.name', '"4CAT"'),
    ('4cat.name_long', '"4CAT: Capture and Analysis Toolkit"'),
    ('4cat.github_url', '"https://github.com/digitalmethodsinitiative/4cat"'),
    ('path.versionfile', '".git-checked-out"'),
    ('expire.timeout', '0'),
    ('expire.allow_optout', 'true'),
    ('logging.slack.level', '"WARNING"'),
    ('logging.slack.webhook', 'null'),
    ('mail.admin_email', 'null'),
    ('mail.host', 'null'),
    ('mail.ssl', 'false'),
    ('mail.username', 'null'),
    ('mail.password', 'null'),
    ('mail.noreply', '"noreply@localhost"'),
    ('SCRAPE_TIMEOUT', '5'),
    ('SCRAPE_PROXIES', '{"http": []}'),
    ('IMAGE_INTERVAL', '3600'),
    ('explorer.max_posts', '100000'),
    ('flask.flask_app', '"webtool/fourcat"'),
    ('flask.secret_key', concat('"', substr(md5(random()::text), 0, 25), '"')),
    ('flask.https', 'false'),
    ('flask.server_name', '"localhost"'),
    ('flask.autologin.name', '"Automatic login"'),
    ('flask.autologin.hostnames', '["localhost"]'),
    ('flask.autologin.api', '["localhost"]')
    ON CONFLICT DO NOTHING;
