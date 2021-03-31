"""
Convert a Twitter NDJSON file to be importable by TCAT's import-jsondump.php
"""
import json
import datetime

from backend.abstract.processor import BasicProcessor
from backend.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "d.l.wahl@uva.nl"

class ConvertNDJSONToJSON(BasicProcessor):
    """
    Convert a Twitter NDJSON file to be importable by TCAT's import-jsondump.php
    """
    type = "convert-ndjson-for-tcat"  # job type ID
    category = "Conversion"  # category
    title = "Convert to TCAT JSON"  # title displayed in UI
    description = "Convert a NDJSON Twitter file to TCAT JSON format"  # description displayed in UI
    extension = "json"  # extension of result file, used internally and in UI

    # TODO: Unsure what the following is for
    # all post-processors with CSV output
    # accepts = ["search", "collocations", "count-posts", "debate_metrics", "get-entities",
    # 		   "extract-nouns", "hatebase-data", "penelope-semanticframe", "quote-ranker",
    # 		   "tfidf", "thread-metadata", "sentence-split", "hatebase-frequencies",
    # 		   "count-countries", "top-images", "url-extractor", "extract-usernames", "vector-ranker",
    # 		   "count-words", "youtube-metadata", "attribute-frequencies", "count-posts"]

    input = "ndjson"
    output = "json"

    def process(self):
        """
        This takes a Twitter NDJSON file to be importable as a JSON file by TCAT's import-jsondump.php
        """
        posts = 0
        self.dataset.update_status("Converting posts")

        # we write to file per row, instead of json.dumps()ing all of it at
        # once, since else we risk having to keep a lot of data in memory,
        # and this buffers one row at most
        with self.dataset.get_results_path().open("w") as output:
            output.write("[")
            for post in self.iterate_items(self.source_file, bypass_map_item=True):
                # stop processing if worker has been asked to stop
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while processing NDJSON file")

                posts += 1

                if posts > 1:
                    output.write(",")

                post = self.map_to_TCAT(post)

                output.write(json.dumps(post))
            output.write("]")

        self.dataset.update_status("Finished.")
        self.dataset.finish(num_rows=posts)

    def map_to_TCAT(self, tweet):
        """
        Map a the ndjson Tweet object to expected TCAT input

        :param tweet:  Tweet object as originally returned by the Twitter API
        :return dict:  Dictionary/JSON in the format expected by TCAT's import-jsondump.php
        """
        new_tweet = {
                    'id_str' : tweet['id'],
                    'created_at' : tweet['created_at'],
                    'user' : {
                              'screen_name' : tweet.get('author_user').get('username'),
                              'id_str' : tweet.get('author_user').get('id'),
                              'statuses_count' : tweet.get('author_user').get('public_metrics').get('tweet_count'),
                              'followers_count' : tweet.get('author_user').get('public_metrics').get('followers_count'),
                              'listed_count' : tweet.get('author_user').get('public_metrics').get('listed_count'),
                              'friends_count' : tweet.get('author_user').get('public_metrics').get('following_count'),
                              'name' : tweet.get('author_user').get('name'),
                              'description' : tweet.get('author_user').get('description'),
                              'url' : tweet.get('author_user').get('url'),
                              'verified' : tweet.get('author_user').get('verified'),
                              'profile_image_url' : tweet.get('author_user').get('profile_image_url'),
                              'created_at' : tweet.get('author_user').get('created_at'),
                              'location' : tweet.get('author_user').get('location'),
                              'withheld_in_countries' : tweet.get('author_user').get('withheld', {}).get('country_codes') if tweet.get('author_user').get('withheld') else None,

                              # Not used by TCAT
                              'protected' : tweet.get('author_user').get('protected'),
                              'pinned_tweet_id' : tweet.get('author_user').get('pinned_tweet_id'),
                              'entities' : tweet.get('author_user').get('entities'),

                             },
                    'source' : tweet['source'],
                    'lang' : tweet.get('lang'),
                    'possibly_sensitive' : tweet.get('possibly_sensitive'),
                    'withheld_copyright' : tweet.get('withheld', {}).get('copyright') if tweet.get('withheld') else None,
                    'withheld_in_countries' : tweet.get('withheld', {}).get('country_codes') if tweet.get('withheld') else None,
                    'retweet_count' : tweet.get('public_metrics').get('retweet_count'),
                    'favorite_count' : tweet.get('public_metrics').get('like_count'),

                    'text': tweet['text'],

                    'entities' : {
                                  'user_mentions' : tweet.get('entities', {}).get('mentions') if tweet.get('entities') else None,
                                  'hashtags' : tweet.get('entities', {}).get('hashtags'),
                                  'urls' : tweet.get('entities', {}).get('urls', []),

                                  # Not used by TCAT
                                  'cashtags' : tweet.get('entities', {}).get('cashtags'),
                                  'annotations' : tweet.get('entities', {}).get('annotations'),

                                  # Media is stored in attachements with APIv2
                                  'media' : self.media_item(tweet.get('attachments', {}).get('media_keys')) if tweet.get('attachments', {}).get('media_keys') else None,
                                 },

                    # Geo data currently has option of place_id and place_id's can have coordinates
                    'place' : {'id' : tweet.get('geo', {}).get('place_id')},
                    'geo' : tweet.get('geo', {}).get('coordinates', {}).get('coordinates') if tweet.get('geo', {}).get('coordinates') else None,

                    # Reply
                    'in_reply_to_user_id_str' : tweet.get('in_reply_to_user_id'),
                    'in_reply_to_screen_name' : tweet.get('in_reply_to_user', {}).get('username'),
                    # Relies on fact that there will only ever be one reply_to tweet in reference_tweets
                    'in_reply_to_status_id_str' : next((reply.get('id') for reply in tweet.get('referenced_tweets', []) if reply.get('type') == 'replied_to'), None),

                    # Quote (also relies on only one quote tweet in reference_tweets)
                    'quoted_status_id_str' : next((quote.get('id') for quote in tweet.get('referenced_tweets', []) if quote.get('type') == 'quoted'), None),

                    # Not used by TCAT
                    'reply_count' : tweet.get('public_metrics').get('reply_count'),
                    'quote_count' : tweet.get('public_metrics').get('quote_count'),
                    'attachements' : {'poll_ids' : tweet.get('attachments', {}).get('poll_ids') if tweet.get('attachments') else None},
                    'context_annotations' : tweet.get('context_annotations'),
                    'conversation_id' : tweet.get('conversation_id'),
                    'reply_settings' : tweet.get('reply_settings'),
                    # Remaining in_reply_to_user information
                    'in_reply_to_user' : tweet.get('in_reply_to_user'),
                    # Storing the full referenced tweets (retweets, quotes, and replies)
                    'referenced_tweets' : tweet.get('referenced_tweets'),
                    }

        # Retweet - TCAT checks existance of 'retweeted_status' as key to determine if tweet is a retweet
        # This assumes only one retweet in reference tweets (which has proven true in testing)
        if any([ref["type"] == "retweeted" for ref in tweet.get("referenced_tweets", [])]):
            new_tweet['retweeted_status'] = self.reformat_retweet(next(retweet for retweet in tweet.get('referenced_tweets') if retweet.get('type') == 'retweeted'))

        return new_tweet

    def reformat_retweet(self, retweet):
        """
        TCAT handles retweets in a few different ways. This mimics the extended context
        query that import-jsondump.php expect. Full retweet is stored as referenced_tweets.
        """
        return {
                'full_text' : retweet.get('text'),
                'id_str' : retweet.get('id'),
                'user' : {'screen_name' : retweet.get('username')},
                'entities' : {
                              'user_mentions' : retweet.get('entities', {}).get('mentions'),
                              'hashtags' : retweet.get('entities', {}).get('hashtags'),
                              'urls' : retweet.get('entities', {}).get('urls'),

                              # Media is stored in attachements with APIv2
                              'media' : retweet.get('attachments', {}).get('media_keys') if retweet.get('attachments') else None,

                              # Not used by TCAT
                              'cashtags' : retweet.get('entities', {}).get('cashtags'),
                              'annotations' : retweet.get('entities', {}).get('annotations'),
                             }
                }
    def media_item(self, tweet_media):
        """
        Some media items return only a string while others return more robust items.
        The string appears to be a key referencing a videos.

        Twitter APIv2 does not have media_url_https, url_expanded, resize (under sizes->large), or indices
        as requested by TCAT.

        """
        new_list = []
        for media in tweet_media:
            if type(media) == dict:
                new_list.append({
                    'id_str' : media.get('media_key'),
                    'url' : media.get('url') if media.get('url') else media.get('preview_image_url'),
                    'expanded_url' : None,
                    'media_url_https' : None,
                    'type' : media.get('type'),
                    'sizes' : {'large' : {'w' : media.get('width'), 'h' : media.get('height'), 'resize' : None}}
                    })
            else:
                # Media Key only
                new_list.append({'id_str' : media, 'url' : None, 'expanded_url' : None, 'media_url_https' : None, 'type' : None})
        return new_list
