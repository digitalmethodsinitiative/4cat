-- jobs table
CREATE TABLE IF NOT EXISTS jobs (
  id          SERIAL PRIMARY KEY,
  jobtype     text    DEFAULT 'misc',
  remote_id   text,
  details     text,
  timestamp   integer,
  claim_after integer DEFAULT 0,
  claimed     integer DEFAULT 0,
  attempts    integer DEFAULT 0
);

-- enforce
CREATE UNIQUE INDEX IF NOT EXISTS unique_job
  ON jobs (
    jobtype,
    remote_id
  );

-- threads
CREATE TABLE IF NOT EXISTS threads (
  id                 bigint PRIMARY KEY, -- matches 4chan thread ID
  board              text,
  timestamp          integer DEFAULT 0, -- first known timestamp for this thread
  timestamp_archived integer DEFAULT 0,
  timestamp_scraped  integer, -- last timestamp this thread was scraped
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
  ON threads (
    timestamp
  );

-- posts
CREATE TABLE IF NOT EXISTS posts (
  id                bigint PRIMARY KEY, -- matches 4chan post ID
  thread_id         bigint,
  timestamp         integer,
  timestamp_deleted integer DEFAULT 0,
  subject           text,
  body              text,
  body_vector       text,
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
  unsorted_data     text,
  body_vector       tsvector
);

CREATE INDEX IF NOT EXISTS posts_timestamp
  ON posts (
    timestamp
  );

CREATE INDEX IF NOT EXISTS posts_thread
  ON posts (
    thread_id
  );

CREATE INDEX IF NOT EXISTS posts_fts
  ON posts
  USING gin (body_vector);

-- post replies
CREATE TABLE IF NOT EXISTS posts_mention (
  post_id      bigint,
  mentioned_id bigint
);

CREATE INDEX IF NOT EXISTS mention_post
  ON posts_mention (
    post_id
  );

CREATE INDEX IF NOT EXISTS mention_mentioned
  ON posts_mention (
    mentioned_id
  );