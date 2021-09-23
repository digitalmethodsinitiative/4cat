-- 8kun
-- threads
CREATE TABLE IF NOT EXISTS threads_8kun (
  id                 text, -- matches 8kun thread ID
  id_seq             SERIAL PRIMARY KEY,  -- sequential ID for easier indexing
  board              text,
  timestamp          integer DEFAULT 0, -- first known timestamp for this thread, i.e. timestamp of first post
  timestamp_archived integer DEFAULT 0,
  timestamp_scraped  integer, -- last timestamp this thread was scraped
  timestamp_deleted  integer DEFAULT 0,  -- timestamp this thread was no longer scrapeable
  timestamp_modified integer, -- last timestamp this thread was modified (reported by 8kun)
  post_last          bigint, -- ID of last post in this thread
  num_unique_ips     integer DEFAULT 0,
  num_replies        integer DEFAULT 0,
  num_images         integer DEFAULT 0,
  limit_bump         boolean DEFAULT FALSE,
  limit_image        boolean DEFAULT FALSE,
  is_sticky          boolean DEFAULT FALSE,
  is_closed          boolean DEFAULT FALSE,
  index_positions    text
);

CREATE UNIQUE INDEX IF NOT EXISTS threads_idboard_8kun
  ON threads_8kun (
    id,
    board
  );

CREATE INDEX IF NOT EXISTS threads_timestamp_8kun
  ON threads_8kun (
    timestamp
  );

CREATE INDEX IF NOT EXISTS threads_seq_8kun
  ON threads_8kun (
    id_seq
  );

-- posts
CREATE TABLE IF NOT EXISTS posts_8kun (
  id                bigint,  -- matches 8kun post ID
  id_seq            SERIAL PRIMARY KEY,  -- sequential ID for easier indexing
  thread_id         text,
  timestamp         integer,
  timestamp_deleted integer DEFAULT 0,
  board             text,
  subject           text,
  body              text,
  author            text,
  author_type       text,
  author_type_id    text,
  author_trip       text,
  country_code      text,
  country_name      text,
  image_file        text,
  image_url         text,
  image_4chan       text,
  image_md5         text,
  image_dimensions  text,
  image_filesize    integer,
  semantic_url      text,
  unsorted_data     text
);

CREATE INDEX IF NOT EXISTS posts_timestamp_8kun
  ON posts_8kun (
    timestamp
  );

CREATE INDEX IF NOT EXISTS posts_thread_8kun
  ON posts_8kun (
    thread_id
  );

CREATE INDEX IF NOT EXISTS posts_seq_8kun
  ON posts_8kun (
    id_seq
  );

CREATE UNIQUE INDEX IF NOT EXISTS posts_idboard_8kun
  ON posts_8kun (
    id,
    board
  );

CREATE TABLE IF NOT EXISTS posts_8kun_deleted (
  id_seq            bigint PRIMARY KEY,
  timestamp_deleted INTEGER DEFAULT 0
);