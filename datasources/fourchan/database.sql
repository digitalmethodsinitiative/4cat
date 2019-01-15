-- 4chan
-- threads
CREATE TABLE IF NOT EXISTS threads_4chan (
  id                 bigint PRIMARY KEY, -- matches 4chan thread ID
  id_seq             SERIAL,  -- sequential ID for easier indexing
  board              text,
  timestamp          integer DEFAULT 0, -- first known timestamp for this thread, i.e. timestamp of first post
  timestamp_archived integer DEFAULT 0,
  timestamp_scraped  integer, -- last timestamp this thread was scraped
  timestamp_deleted  integer DEFAULT 0,  -- timestamp this thread was no longer scrapeable
  timestamp_modified integer, -- last timestamp this thread was modified (reported by 4chan)
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

CREATE INDEX IF NOT EXISTS threads_timestamp
  ON threads_4chan (
    timestamp
  );

CREATE INDEX IF NOT EXISTS threads_seq
  ON threads_4chan (
    id_seq
  );

-- posts
CREATE TABLE IF NOT EXISTS posts_4chan (
  id                bigint PRIMARY KEY,  -- matches 4chan post ID
  id_seq            SERIAL,  -- sequential ID for easier indexing
  thread_id         bigint,
  timestamp         integer,
  timestamp_deleted integer DEFAULT 0,
  subject           text,
  body              text,
  author            text,
  author_type       text,
  author_type_id    text,
  author_trip       text,
  country_code      text,
  country_name      text,
  image_file        text,
  image_4chan       text,
  image_md5         text,
  image_dimensions  text,
  image_filesize    integer,
  semantic_url      text,
  unsorted_data     text
);

CREATE INDEX IF NOT EXISTS posts_timestamp
  ON posts_4chan (
    timestamp
  );

CREATE INDEX IF NOT EXISTS posts_thread
  ON posts_4chan (
    thread_id
  );

CREATE INDEX IF NOT EXISTS posts_seq
  ON posts_4chan (
    id_seq
  );

-- post replies
CREATE TABLE IF NOT EXISTS posts_mention_4chan (
  post_id      bigint,
  mentioned_id bigint
);

CREATE INDEX IF NOT EXISTS mention_post
  ON posts_mention_4chan (
    post_id
  );

CREATE INDEX IF NOT EXISTS mention_mentioned
  ON posts_mention_4chan (
    mentioned_id
  );

-- enforce
CREATE UNIQUE INDEX IF NOT EXISTS unique_mention
  ON posts_mention_4chan (
    post_id,
    mentioned_id
  );