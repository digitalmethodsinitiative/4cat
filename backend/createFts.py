import config
import time
from lib.logger import Logger
from lib.database import Database


"""
	Index and copy the title and post columns, transform to type tsvector for postgres FTS
	NOTE: Isolated file right now, but should be made into a worker later!
	Also only creates column for the body

    ### Init database ###
"""
db = Database(logger=Logger())

# Add column and index for fst data on posts table
db.execute("""
			ALTER TABLE posts ADD "body_vector" tsvector;
			CREATE INDEX idx_fts_post ON posts USING gin(body_vector);
""")

# Update the relevant text column with tsvector data
db.execute("""
			UPDATE posts
			SET body_vector = (to_tsvector(body));
""")

print("Done!")