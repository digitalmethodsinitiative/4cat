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
CREATE TABLE IF NOT EXISTS queries (
  id              SERIAL PRIMARY KEY,
  key             text,
  type            text DEFAULT 'search',
  key_parent      text,
  query           text,
  job             integer DEFAULT 0,
  parameters      text,
  result_file     text DEFAULT '',
  timestamp       integer,
  status          text,
  num_rows        integer DEFAULT 0,
  is_finished     boolean DEFAULT FALSE
);

-- users
CREATE TABLE IF NOT EXISTS users (
  name               TEXT UNIQUE PRIMARY KEY,
  password           TEXT,
  is_admin           BOOLEAN DEFAULT FALSE,
  register_token     TEXT DEFAULT '',
  timestamp_token    INTEGER DEFAULT 0,
  timestamp_seen     INTEGER DEFAULT 0
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