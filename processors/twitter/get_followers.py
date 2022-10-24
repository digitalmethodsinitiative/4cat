"""
Collect user data for a Twitter user's followers
"""
import json

from datasources.twitterv2users.search_twitter_users import SearchUsersWithTwitterAPIv2
from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class GetTwitterFollowers(BasicProcessor):
    """
    Get Twitter followers
    """
    type = "twitterv2-get-followers"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Get followers"  # title displayed in UI
    description = "Retrieves user profiles of all followers of the users in this dataset"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type in ("twitterv2-user-search", "twitterv2-get-followers", "twitterv2-get-following")

    def process(self):
        """
        Get followers!!!!

        :return:
        """

        # this processor can also be used to get accounts followed *by* a user
        # in that case we have a slightly different endpoint and user field to
        # fill - the class is identical otherwise
        endpoint_target = "followers" if self.__class__ is GetTwitterFollowers else "following"
        field = "follows" if self.__class__ is GetTwitterFollowers else "followed_by"

        done = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            for user in self.source_dataset.iterate_items(bypass_map_item=True):
                target = user["username"]

                endpoint = "https://api.twitter.com/2/users/%s/%s" % (str(user["id"]), endpoint_target)
                for follower in SearchUsersWithTwitterAPIv2.fetch_users(self, {"users": target}, endpoint, None):
                    follower[field] = target
                    outfile.write(json.dumps(follower) + "\n")
                    done += 1

        self.dataset.finish(done)

    @staticmethod
    def map_item(item):
        """
        Map Twitter User object to flat dictionary

        Borrow the `map_item()` from the twitter user data source.

        :param dict item:  User to map
        :return dict:  Flattened object
        """
        return SearchUsersWithTwitterAPIv2.map_item(item)

