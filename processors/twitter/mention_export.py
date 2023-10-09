"""
Twitter APIv2 base stats class
"""
import csv

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorException, ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class TwitterMentionsExport(BasicProcessor):
    """
    Collect User stats as both author and mention.
    """
    type = "twitter-mentions-export"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Mentions Export"  # title displayed in UI
    description = "Identifies mentions types and creates mentions table (tweet id, from author id, from username, to user id, to username, mention type)"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type in ["twitterv2-search"]

    def process(self):
        """
        This takes a 4CAT twitter dataset file as input, and outputs a csv.
        """
        self.dataset.update_status("Processing posts")

        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            item = {'tweet_id': None, 'from_user_id': None, 'from_username': None, 'to_user_id': None, 'to_username': None, 'mention_type': None, 'errors': None}
            writer = csv.DictWriter(outfile, fieldnames=item.keys())
            writer.writeheader()

            counter = 0
            # Iterate through each post and collect data for each interval
            for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while processing Tweets")

                item = {
                    'tweet_id': post.get('id'),
                    'from_user_id': post.get("author_id"),
                    'from_username': post.get("author_user").get("username"),
                }
                # Check for Mentions
                mentions = [{'username': tag["username"], 'id': tag['id']} for tag in
                            post.get("entities", {}).get("mentions", [])]
                captured_mentions = set()
                ref_type_matching_error = []

                if item['from_username'] == 'REDACTED':
                    raise ProcessorException("Author information has been removed; cannot proceed")

                retweet = False
                for ref_tweet in post.get('referenced_tweets', []):
                    item['errors'] = error_message = ''
                    item['mention_type'] = ref_tweet.get('type')
                    if ref_tweet.get("author_user", {}).get('username'):
                        item['to_user_id'] = ref_tweet.get("author_id")
                        item['to_username'] = ref_tweet.get("author_user").get("username")
                    else:
                        # Referenced user or tweet was deleted
                        if ref_tweet.get('author_id'):
                            # Check to see if ref_tweet still has author_id
                            matching_user = [mention for mention in mentions if
                                             mention.get('id') == ref_tweet.get('author_id')]
                            item['to_user_id'] = matching_user[0].get('id')
                            item['to_username'] = matching_user[0].get('username')
                        elif len(mentions) == 1 and len(post.get('referenced_tweets', [])) == 1:
                            # Only one referenced tweet and one mention; must be this one!
                            item['to_user_id'] = mentions[0].get('id')
                            item['to_username'] = mentions[0].get('username')
                        else:
                            # Unable to determine which mention is related to this referenced tweet
                            # TODO: Is there any way to confirm that it is *always* the first mention?
                            # Keeping in mind sometime there can be both a quote and replyed_to as reference tweets
                            error_message = 'Unable to match referenced tweet type %s to specific mention (all mentions listed as mention_type "mention" for this tweet) due to: %s' % (item['mention_type'], ref_tweet.get('error').get('detail'))
                            ref_type_matching_error.append(error_message)
                            continue

                    # Add any error data
                    if ref_tweet.get('error'):
                        item['errors'] = 'Tweet %s ' % item['tweet_id'] + error_message if error_message else 'Tweet %s had error for mention type %s: ' % (item['tweet_id'], item['mention_type']) + '%s' % str(ref_tweet.get('error').get('detail'))
                        self.dataset.log(item['errors'])

                    if item['to_username'] not in captured_mentions:
                        writer.writerow(item)
                        captured_mentions.add(item['to_username'])
                        counter += 1

                        if counter % 2500 == 0:
                            self.dataset.update_status("Processed through " + str(counter) + " mentions.")

                    if ref_tweet.get('type') == 'retweeted':
                        retweet = True
                        retweet_mentions = [{'username': tag["username"], 'id': tag['id']} for tag in
                                            post.get("entities", {}).get("mentions", [])]
                    # TODO: Value in logging quoted or replied to mentions from referenced tweets?

                # If Retweet, pass the mentions to the main tweet and change type
                if retweet:
                    # Retweets only contain the mention of the original tweet's author (which should be captured above) and any mentions from the original author
                    ref_type = 'retweeted_mention'
                    mentions.extend(retweet_mentions)
                else:
                    ref_type = 'mention'

                for mention in mentions:
                    item['errors'] = ''
                    item['to_user_id'] = mention.get("id")
                    item['to_username'] = mention.get("username")
                    item['mention_type'] = ref_type

                    if ref_type_matching_error:
                        item['errors'] = ', '.join(ref_type_matching_error)

                    if item['to_username'] not in captured_mentions:
                        writer.writerow(item)
                        captured_mentions.add(item['to_username'])
                        counter += 1

                        if counter % 2500 == 0:
                            self.dataset.update_status("Processed through " + str(counter) + " mentions.")

            self.dataset.update_status("Finished")
            self.dataset.finish(counter)


class TCATMentionsExport(BasicProcessor):
    """
    Collect User stats as both author and mention.
    """
    type = "tcat-mentions-export"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Mentions Export"  # title displayed in UI
    description = "Identifies mentions types and creates mentions table (tweet id, from author id, from username, to username)"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type in ["dmi-tcat-search"]

    def process(self):
        """
        This takes a TCAT imported dataset file as input, and outputs a csv w/ Mention table. TCAT does not retain
        enough information to be sure of the mention type, and it does not included mentioned user IDs.
        """
        self.dataset.update_status("Processing posts")

        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
            item = {'tweet_id': None, 'from_user_id': None, 'from_username': None, 'to_username': None}
            writer = csv.DictWriter(outfile, fieldnames=item.keys())
            writer.writeheader()

            counter = 0
            # Iterate through each post and collect data for each interval
            for post in self.source_dataset.iterate_items(self, bypass_map_item=True):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while processing Tweets")

                item = {
                    'tweet_id': post.get('id'),
                    'from_user_id': post.get("author_id"),
                    'from_username': post.get("author_user").get("username"),
                }
                # Check for Mentions
                mentions = [tag["username"] for tag in
                            post.get("entities", {}).get("mentions", [])]
                captured_mentions = set()

                if item['from_username'] == 'REDACTED':
                    raise ProcessorException("Author information has been removed; cannot proceed")

                for mention in mentions:
                    item['to_username'] = mention

                    if item['to_username'] not in captured_mentions:
                        writer.writerow(item)
                        captured_mentions.add(item['to_username'])
                        counter += 1

                        if counter % 2500 == 0:
                            self.dataset.update_status("Processed through " + str(counter) + " mentions.")

            self.dataset.update_status("Finished")
            self.dataset.finish(counter)
