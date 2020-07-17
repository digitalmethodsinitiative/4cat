CREATE TABLE IF NOT EXISTS posts_usenet (
  id          TEXT UNIQUE,
  id_seq      SERIAL,  -- sequential ID for easier indexing
  thread_id   TEXT,
  timestamp   INTEGER,
  subject     TEXT,
  author      TEXT,
  body        TEXT,
  headers     TEXT,
  groups      TEXT
);

CREATE TABLE IF NOT EXISTS threads_usenet (
  id          TEXT UNIQUE,
  id_seq      SERIAL,  -- sequential ID for easier indexing
  timestamp   INTEGER,
  board       TEXT DEFAULT '',
  num_replies INTEGER DEFAULT 0,
  post_last   TEXT,
  post_first  TEXT
);

CREATE TABLE IF NOT EXISTS groups_usenet (
  post_id TEXT,
  "group" TEXT
);