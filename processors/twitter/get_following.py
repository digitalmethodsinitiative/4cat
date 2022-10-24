"""
Collect user data for a Twitter user's followed accounts
"""

from processors.twitter.get_followers import GetTwitterFollowers

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class GetTwitterFollowing(GetTwitterFollowers):
    """
    Get Twitter followers
    """
    type = "twitterv2-get-following"  # job type ID
    category = "Twitter Analysis"  # category
    title = "Get followed accounts"  # title displayed in UI
    description = "Retrieves user profiles of all accounts followed by the users in this dataset"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    # no further class body - is inherited from GetTwitterFollowers
