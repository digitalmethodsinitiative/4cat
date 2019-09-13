CREATE TABLE posts_breitbart
(
  id_seq          SERIAL PRIMARY KEY,
  id              BIGINT UNIQUE,
  thread_id       BIGINT,
  subject         TEXT,
  body            TEXT,
  timestamp       INTEGER,
  author          TEXT,
  author_location TEXT,
  author_name     TEXT,
  likes           INTEGER,
  dislikes        INTEGER,
  reply_to        BIGINT

);

CREATE TABLE threads_breitbart
(
  id_seq            SERIAL PRIMARY KEY, -- sequential ID for easier indexing
  id                INTEGER UNIQUE,     -- matches breitbart thread ID
  timestamp         INTEGER DEFAULT 0,  -- first known timestamp for this thread, i.e. timestamp of first post
  timestamp_scraped INTEGER,            -- last timestamp this thread was scraped
  post_first        BIGINT,             -- ID of first reply
  post_last         BIGINT,             -- ID of last post in this thread
  post_amount       integer DEFAULT 0,
  url               TEXT,
  section           TEXT,
  tags              TEXT    DEFAULT '',
  disqus_id         TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS threads_timestamp_breitbart
  ON threads_breitbart (
                        timestamp
    );

CREATE INDEX IF NOT EXISTS threads_seq_breitbart
  ON threads_breitbart (
                        id_seq
    );

CREATE INDEX IF NOT EXISTS posts_timestamp_breitbart
  ON posts_breitbart (
                      timestamp
    );

CREATE INDEX IF NOT EXISTS posts_thread_breitbart
  ON posts_breitbart (
                      thread_id
    );

CREATE INDEX IF NOT EXISTS posts_seq_breitbart
  ON posts_breitbart (
                      id_seq
    );