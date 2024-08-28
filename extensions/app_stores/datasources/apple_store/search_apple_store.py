import time
import datetime
import re
import json
import requests

from google_play_scraper.scraper import PlayStoreScraper
from itunes_app_scraper.scraper import AppStoreScraper

from google_play_scraper.util import PlayStoreException
from itunes_app_scraper.util import AppStoreException, AppStoreCollections

from google_play_scraper.util import PlayStoreCollections
from itunes_app_scraper.util import AppStoreCollections


from backend.lib.search import Search
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput


class AppStoreConnectionError(Exception):
    pass

class SearchAppleStore(Search):
    """
    Search Apple Store data source


    Defines methods to fetch data from Apples application store on demand
    """
    type = "apple-store-search"  # job ID
    category = "Search"  # category
    title = "Apple Store Search"  # title displayed in UI
    description = "Query Apple's app store to retrieve data on applications and developers"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # This mapping matches the method names in the collect_from_store function
    # method names in options use "requires" for the frontend to show/hide options
    option_to_method = {
            'query-app-detail': 'app',
            'list-detail': 'list',
            'query-search-detail': 'search',
            'query-developer-detail': 'developer',
            'query-similar-detail': 'similar',
            'query-permissions': 'permissions',
        }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):

        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": ("This data source allows you to query Apple's app store to retrieve data on applications and developers."
                         "\nCountry options can be found [here](https://osf.io/8pn7w) and represent different [app \"stores\"](https://www.apple.com/choose-country-region/)."
                         " For the Apple Store, language does not appear to affect which results are returned for queries, but does affect the language of the results for beta details .")
            },
            "method": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Query Type",
                "options": {
                    "query-app-detail": "App IDs",
                    "list-detail": "Apple App Collection",
                    "query-search-detail": "Search by query",
                    "query-developer-detail": "Developer IDs",
                    "query-similar-detail": "Similar Apps",
                    # "query-permissions": "Permissions", # Permissions do not exist for apple store!
                },
                "default": "query-search-detail"
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of App IDs, Developer IDs, or queries to search for.",
                "requires": "method^=query", # starts with query
                "tooltip": "Seperate IDs or queries with commas to search multiple.",
                "default": "", # need default else regex will fail
            },
            "collection": {
                "type": UserInput.OPTION_INFO,
                "help": "Apple Store App Collection",
                "requires": "method^=list", # starts with list
            },
            "full_details": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include full application details",
                "default": False,
                "tooltip": "If enabled, the full details of each application will be included in the output.",
                "requires": "method$=detail", # ends with detail
            },
            "beta_details": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Use new beta details endpoint",
                "default": False,
                "tooltip": "If enabled, the full details will be collected from apps.apple.com.",
                "requires": "full_details==true",
            },
            "intro-2": {
                "type": UserInput.OPTION_INFO,
                "help": "Language and Country options have limited effects due to geographic restrictions and results given based on from what country the request originates (i.e. the country where 4CAT is based)."
            },
            "languages": {
                "type": UserInput.OPTION_TEXT,
                "help": "Languages to query.",
                "default": "en",
                "tooltip": "Seperate ISO two letter language codes with commas to search multiple languages. If left blank, only English will be used."
            },
            "countries": {
                "type": UserInput.OPTION_TEXT,
                "help": "Countries to query.",
                "default": "us",
                "tooltip": "Seperate ISO two letter country codes with commas to search multiple countries. If left blank, only US will be used."
            },
        }
        collections = {collection: getattr(AppStoreCollections, str(collection)) for collection in dir(AppStoreCollections) if not collection.startswith('__')}
        if len(collections) > 0:
            options["collection"]["type"] = UserInput.OPTION_CHOICE
            options["collection"]["options"] = {k:k for k,v in collections.items()}
            options["collection"]["default"] = list(collections.keys())[0]
        else:
            options.pop("collection")
        
        return options

    def get_items(self, query):
        """
        Fetch items from Apple Store

        :param query:
        :return:
        """
        queries = re.split(',|\n', self.parameters.get('query', ''))
        # Updated method from options to match the method names in the collect_from_store function
        method = self.option_to_method.get(self.parameters.get('method'))
        if method is None:
            self.log.warning(f"Apple store unknown query method; check option_to_method dictionary matches method options.")

        params = {}
        if method == 'list':
            params['collection'] = self.parameters.get('collection')
        elif method == 'search':
            params['queries'] = queries
        elif method == 'developer':
            params['devId'] = queries
        elif method == 'similar':
            params['appId'] = queries
        elif method == 'permissions':
            params['appId'] = queries
        else:
            params['appId'] = queries

        results = []

        if not self.parameters.get('beta_details', False):
            self.dataset.log(f"Collecting {method} from Apple Store")
            results += collect_from_store('apple', method, languages=re.split(',|\n', self.parameters.get('languages')), countries=re.split(',|\n', self.parameters.get('countries')), full_detail=self.parameters.get('full_details', False), params=params, log=self.dataset.log)
        else:
            self.dataset.update_status("Collecting results with new beta endpoint")
            if method != 'app':
                list_of_apps = collect_from_store('apple', method, languages=re.split(',|\n', self.parameters.get('languages')), countries=re.split(',|\n', self.parameters.get('countries')), params=params, log=self.dataset.log)
            else:
                list_of_apps = queries

            for i, app in enumerate(list_of_apps):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while getting collecting detailed results from Apple Store")
                if method != 'app':
                    lang = app.get('lang', 'en-US')
                    country = app.get('country', 'us')
                    try:
                        results.append(self.collect_detailed_data_from_apple_store_by_id(app['id'], country, lang))
                    except AppStoreConnectionError as e:
                        self.dataset.update_status(f"Error collecting app {app['id']}: {e}")
                        continue
                else:
                    # List of apps only contains IDs
                    # TODO: issue w/ languages and countries; likely codes
                    # languages = [lang.strip() for lang in self.parameters.get('languages')] if self.parameters.get('languages') else []
                    # countries = [country.strip() for country in self.parameters.get('countries')] if self.parameters.get('countries') else []
                    # for country in countries:
                    #     for language in languages:
                    if self.interrupted:
                        raise ProcessorInterruptedException("Interrupted while getting collecting detailed results from Apple Store")
                    try:
                        results.append(self.collect_detailed_data_from_apple_store_by_id(app))#, country, language))
                    except AppStoreConnectionError as e:
                        self.dataset.update_status(f"Error collecting app {app['id']}: {e}")
                        continue
        if results:
            self.dataset.log(f"Collected {len(results)} results from Apple Store")
            return [{"4CAT_metadata": {"query_method": method, "collected_at_timestamp": datetime.datetime.now().timestamp(), "item_index": i, "beta": self.parameters.get('beta_details', False)}, **result} for i, result in enumerate(results)]
        else:
            self.dataset.log(f"No results identified for {self.parameters.get('query', '') if method != 'lists' else self.parameters.get('collection')} from Apple Store")
            return []

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
           
        return query

    @staticmethod
    def map_beta_item(item, fourcat_metadata, preferred_platform="ios"):

        if any([key not in ["id", "type", "href", "attributes", "relationships", "meta"] for key in item.keys()]):
            # Additional unknown information in item!
            pass

            # General App attributes located here
        app_attributes = item["attributes"]

        # Possible to have multiple platforms which in tern have different release dates, version histories, etc.
        platform_preferences = preferred_platform if type(preferred_platform) is list else [preferred_platform]
        if any([pref in app_attributes.get("platformAttributes") for pref in platform_preferences]):
            # Collect first from preffered_platforms
            for platform_preference in platform_preferences:
                if platform_preference in app_attributes.get("platformAttributes"):
                    platform_data = app_attributes.get("platformAttributes").get(platform_preference)
                    platform = platform_preference
                    other_platforms = [key for key in app_attributes.get("platformAttributes").keys() if key != platform_preference]
                    break
        else:
            # Grab first available
            platform = next(iter(app_attributes.get("platformAttributes")))
            platform_data = app_attributes.get("platformAttributes").get(platform)
            other_platforms = [key for key in app_attributes.get("platformAttributes").keys() if key != platform]

        # All screenshots
        # Note: some screenshots repeat as different sizes for different versions (e.g., pre and post iphone 6)
        screenshots = []
        for screenshot_type, screenshot_data in platform_data.get("customAttributes", {}).get("default", {}).get(
                "default", {}).get("customScreenshotsByType").items():
            for screenshot in screenshot_data:
                screenshots.append(convert_screenshot(screenshot))

        # Genres are a relationship item
        genres, genre_ids = zip(*[(genre.get("attributes", {}).get("name"), genre.get("id", "")) for genre in item.get('relationships').get("genres").get("data")])

        # Supported locale info
        if platform_data.get("supportedLocales"):
            locale_names, locale_tags = zip(*[(locale.get("name"), locale.get("tag")) for locale in platform_data.get("supportedLocales")])
        else:
            locale_names, locale_tags = [], []

        # Content rating
        if len(app_attributes.get("contentRatingsBySystem")) > 1:
            # More than one!
            pass
        content_rating = app_attributes.get("contentRatingsBySystem")[next(iter(app_attributes.get("contentRatingsBySystem")))]

        # Developer
        if len(item.get("relationships").get("developer", {}).get("data", [])) > 1:
            # More than one!
            pass
        developer = item.get("relationships").get("developer", {}).get("data", [])[0]

        # Purchase options
        offers = [offer for offer in platform_data.get("offers") if offer.get("type") == "buy"]
        if len(offers) > 1:
            # multiple purchase offers is possible...
            pass
        offer = offers[0] if offers else None

        return {
            "4CAT_query_type": fourcat_metadata["query_method"],
            # Extract country & language from URL as it may not match query; requested lang may exist or store may redirect
            "country": item.get("href").split("/v1/catalog/")[1].split("/")[0],
            "language": item.get("href").split("?l=")[1].split("&")[0] if "?l=" in item.get("href") else "",
            "app_id": item.get("id"),
            "app_name": app_attributes.get("name"),
            "app_view_url": app_attributes.get("url"),

            # Developer data
            "developer_id": developer.get("id", ""),
            "developer_name": app_attributes.get("artistName", ""),
            "developer_view_url": developer.get("attributes", {}).get("url", ""),

            # Platform specific data
            "platform": platform,
            "other_available_platforms": ", ".join(other_platforms),
            "release_date": platform_data.get("releaseDate"),
            "current_version_release_date": platform_data.get("versionHistory")[0].get("releaseTimestamp", ""),
            "current_version": platform_data.get("versionHistory")[0].get("versionDisplay", ""),
            "current_version_release_notes": platform_data.get("versionHistory")[0].get("releaseNotes", ""),
            "description": platform_data.get("description").get("standard"),
            # Many different sizes are listed, but the displayed size appears to be located in the assets (noted types of "get", "buy", and "update")
            "file_size_bytes": next(iter(
                [next(iter(offer.get("assets", []))).get("size") for offer in platform_data.get("offers") if
                 offer.get("type") in ["buy", "get"]])),
            "is_game_center_enabled": platform_data.get("isGameCenterEnabled", ""),
            "seller_name": platform_data.get("seller", ""),
            "bundle_id": platform_data.get("bundleId", ""),
            "minimum_os_version": platform_data.get("minimumOSVersion", ""),

            # Purchase info
            "price": offer.get("price", "") if offer else "",
            "formatted_price": offer.get("formattedPrice", "").replace(u'\xa0', u' ') if offer else "Free",
            "currency": offer.get("currencyCode", "") if offer else "",
            "has_in_app_purchases": platform_data.get("hasInAppPurchases", ""),

            # Genre
            "primary_genre_name": app_attributes.get("genreDisplayName", ""),
            "genres": ", ".join(genres),
            "genre_ids": ", ".join(genre_ids),

            # Images
            "app_logo": convert_screenshot(platform_data.get("artwork")),
            "brand_images": ",\n".join(
                [convert_screenshot(image) for name, image in platform_data.get("editorialArtwork").items()]),
            "screenshot_urls": ",\n".join(screenshots),

            # Advisories
            "age_rating": content_rating.get("name"),
            "advisories": ",\n".join(content_rating.get("advisories", [])),

            # Privacy
            "private_policy_url": platform_data.get("privacyPolicyUrl", ""),
            "data_collected": ",\n".join([
                                            f"{privacy_type.get('privacyType', '')}: {', '.join([data_type.get('dataCategory', '') for data_type in privacy_type.get('dataCategories', [])])}"
                                            for privacy_type in
                                            app_attributes.get("privacy", {}).get("privacyTypes", [])]),

            # Additional info
            "supported_devices": ", ".join(
                [device for k, v in app_attributes.get("requirementsByDeviceFamily").items() for device in
                 (v.get('devices') if v.get('devices') else [v.get('deviceFamily')])]),
            "supported_locales": ", ".join(locale_names),
            "supported_locale_tags": ", ".join(locale_tags),

            # Charts
            "top_charts": ",\n".join([f"{camel_to_title(source)} chart: {chart.get('position')} on {case_to_title(chart.get('chart'))}{' in ' + chart.get('genreName') if 'genreName' in chart else ''}" for source, chart in app_attributes.get("chartPositions", {}).items()]),

            # In app purchases
            "in-app_purchases": ",\n".join([
                                              f"{app_purchase.get('attributes', {}).get('name', {})} - {next(iter(app_purchase.get('attributes', {}).get('offers', []))).get('priceFormatted', '')}".replace(
                                                  u'\xa0', u' ') for app_purchase in
                                              item.get("relationships").get("top-in-apps", {}).get("data", [])]),
            # Events
            "events": ",\n".join(
                [f"{event.get('attributes', {}).get('name', {})} - {event.get('attributes', {}).get('url', '')}" for
                 event in item.get("relationships").get("app-events", {}).get("data", [])]),
            # Apple editorials related to the app
            "related_editorials": "\n".join([
                                                f"{editorial.get('attributes', {}).get('editorialNotes', {}).get('name', '')} - {editorial.get('attributes', {}).get('url', '')}"
                                                for editorial in
                                                item.get("relationships").get("related-editorial-items", {}).get("data",
                                                                                                                 [])]),

            # Ratings
            "user_rating_count": app_attributes.get('userRating', {}).get('ratingCount', ''),
            "average_user_rating": app_attributes.get('userRating', {}).get('value', ''),
            "user_ratings": ", ".join([f"{i + 1} star{'s' if i != 0 else ''}: {num}" for i, num in
                             enumerate(app_attributes.get('userRating', {}).get('ratingCountList', []))]),

            # Ten reviews are shared
            "reviews": ",\n".join([
                                     f"{review.get('attributes', {}).get('title', {})} - rating {review.get('attributes', {}).get('rating', {})} - {review.get('attributes', {}).get('review', '')}"
                                     for review in item.get("relationships").get("reviews", {}).get("data", [])]),

            # Version history
            "recent_versions": ",\n".join([
                                             f"{version.get('releaseTimestamp', '')} - {version.get('versionDisplay', '')}: {version.get('releaseNotes', '')}"
                                             for version in platform_data.get("versionHistory", [])]),

            # 4CAT necessary fields
            "collected_timestamp": fourcat_metadata.get("collected_at_timestamp", ""),
            "id": item.get("id"),
            "author": app_attributes.get("artistName", ""),
            "body": platform_data.get("description").get("standard"),
            "timestamp": platform_data.get("releaseDate"),
        }
    
    @staticmethod
    def map_item(item):
        """
        Map item to a common format that includes, at minimum, "id", "thread_id", "author", "body", and "timestamp" fields.

        :param item:
        :return:
        """
        if "4CAT_metadata" in item:
            fourcat_metadata = item.pop("4CAT_metadata")
            if fourcat_metadata.get("beta", False):
                return MappedItem(SearchAppleStore.map_beta_item(item, fourcat_metadata))
            else:
                query_method = fourcat_metadata.get("query_method", "")
                collected_timestamp = fourcat_metadata.get("collected_at_timestamp", "")
        else:
            query_method = item.pop("query_method", "")
            collected_timestamp = item.pop("collected_at_timestamp", "")

        formatted_item = {
            "4CAT_query_type": query_method,
            "query_country": item.get("country", ""),
            "query_language": item.get("lang", ""),
            }

        if query_method == 'app':
            formatted_item["id"] = item.get("trackId")
        elif query_method == 'list':
            formatted_item["id"] = item.get("trackId")
        elif query_method == 'search':
            formatted_item["4CAT_query_term"] = item.pop("term", "")
            formatted_item["id"] = item.get("id", item.get("trackId", "")) # detailed search returns trackId, simple search returns id
        elif query_method == 'developer':
            formatted_item["id"] = item.get("trackId")
        elif query_method == 'similar':
            formatted_item["id"] = item.get("id")
        else:
            # Should not happen
            raise Exception("Unknown query method: {}".format(query_method))

        formatted_item["app_id"] = item.get("id", item.get("trackId", ""))
        # Map expected fields which may be missing and rename as desired
        mapped_fields = {
            "releaseDate": "release_date",
            "currentVersionReleaseDate": "current_version_release_date",
            "artistId": "developer_id",
            "artistName": "developer_name",
            "artistViewUrl": "developer_url",
            "sellerName": "seller_name",
            "sellerUrl": "seller_url",
            "trackId": "app_id",
            "trackName": "app_name",
            "description": "description",
            "genres": "genres",
            "primaryGenreName": "primary_genre_name",
            "primaryGenreId": "primary_genre_id",
            "genreIds": "genre_ids",
            "kind": "kind",
            "version": "version",
            "fileSizeBytes": "file_size_bytes",
            "screenshotUrls": "screenshot_urls",
            "ipadScreenshotUrls": "ipad_screenshot_urls",
            "appletvScreenshotUrls": "appletv_screenshot_urls",
            "artworkUrl60": "artwork_url_60",
            "artworkUrl512": "artwork_url_512",
            "artworkUrl100": "artwork_url_100",
            "isGameCenterEnabled": "is_game_center_enabled",
            "features": "features",
            "advisories": "advisories",
            "supportedDevices": "supported_devices",
            "trackCensoredName": "app_censored_name",
            "languageCodesISO2A": "language_codes_iso2a",
            "contentAdvisoryRating": "content_advisory_rating",
            "userRatingCount": "user_rating_count",
            "user_ratings": "user_ratings",
            "averageUserRating": "average_user_rating",
            "averageUserRatingForCurrentVersion": "average_user_rating_for_current_version",
            "userRatingCountForCurrentVersion": "user_rating_count_for_current_version",
            "trackViewUrl": "app_view_url",
            "trackContentRating": "app_content_rating",
            "releaseNotes": "release_notes",
            "price": "price",
            "formattedPrice": "formatted_price",
            "currency": "currency",
            "bundleId": "bundle_id",
            "isVppDeviceBasedLicensingEnabled": "is_vpp_device_based_licensing_enabled",
            "minimumOsVersion": "minimum_os_version",
            "wrapperType": "wrapper_type",
            "errors": "errors",
        }

        for field in mapped_fields:
            formatted_item[mapped_fields[field]] = item.get(field, "")

        # Add any additional fields to the item
        formatted_item["additional_data_in_ndjson"] = ", ".join(
            [f"{key}: {value}" for key, value in item.items() if key not in list(mapped_fields) +  ["id"]])

        # 4CAT required fields
        formatted_item["collected_timestamp"] = collected_timestamp
        formatted_item["thread_id"] =  ""
        formatted_item["author"] = item.get("artistName", "")
        formatted_item["body"] = item.get("description", "")
        # some queries do not return a publishing timestamp so we use the collected at timestamp
        formatted_item["timestamp"] = datetime.datetime.strptime(item.get("releaseDate"), "%Y-%m-%dT%H:%M:%SZ") if "releaseDate" in item else collected_timestamp

        return MappedItem(formatted_item)

    @staticmethod
    def collect_detailed_data_from_apple_store_by_id(app_id, country_id="us", lang="en-us"):
        """
        Collect App details from Apple Store

        This is to take advantage of a different endpoint found from looking up apps at https://apps.apple.com/.
        """
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
        # Collect token
        token_url = f"https://apps.apple.com/{country_id}/app/id{app_id}"
        response = requests.get(token_url, headers={'User-Agent': user_agent})
        if response.status_code != 200:
            raise Exception(f"Unable to connect to apps.apple.com: {response.status_code} {response.reason}")
        html = response.text

        reg_exp = re.compile(r'token%22%3A%22([^%]+)%22%7D')
        match = reg_exp.search(html)
        token = match.group(1)
        if not token:
            raise Exception("Unable to find token to collect data from apps.apple.com")

        # Collect data
        # Copied from browser request
        url = f"https://amp-api.apps.apple.com/v1/catalog/{country_id}/apps/{app_id}?l={lang}&platform=web&additionalPlatforms=appletv,ipad,iphone,mac&" \
              "extend=customPromotionalText,customScreenshotsByType,customVideoPreviewsByType,description,developerInfo,distributionKind,editorialVideo,fileSizeByDevice,messagesScreenshots,privacy,privacyPolicyUrl,requirementsByDeviceFamily,sellerInfo,supportURLForLanguage,versionHistory,websiteUrl,videoPreviewsByType&" \
              "include=app-events,genres,developer,reviews,merchandised-in-apps,customers-also-bought-apps,developer-other-apps,top-in-apps,related-editorial-items&" \
              "limit[merchandised-in-apps]=20&" \
              "omit[resource]=autos&" \
              "meta=robots&" \
              "sparseLimit[apps:related-editorial-items]=20&" \
              "sparseLimit[apps:customers-also-bought-apps]=20&" \
              "sparseLimit[app:developer-other-apps]=20"

        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://apps.apple.com',
            'Authorization': f"Bearer {token}",
            'User-Agent': user_agent
        }

        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            try:
                json_data = json.loads(response.text)
            except json.JSONDecodeError:
                json_data = {}

            if "Invalid Parameter Value" in [error.get("title", '') for error in json_data.get("errors", [])]:
                raise AppStoreConnectionError(f"Invalid Parameter Value: {' '.join([error.get('detail', '') for error in json_data.get('errors', [])])}")
            else:
                raise Exception(f"Unable to collect data from apps.apple.com: {response.status_code} {response.reason} - {response.text}")

        if len(response.text) == 0:
            raise ValueError(f"No result returned: app - {app_id}, country - {country_id}, lang - {lang}")

        data = json.loads(response.text)
        if not data.get('data'):
            raise ValueError(f"App not found (404): app - {app_id}, country - {country_id}, lang - {lang}")
        elif len(data['data']) == 0:
            raise ValueError(f"App not found (404): app - {app_id}, country - {country_id}, lang - {lang}")
        elif len(data['data']) > 1:
            raise ValueError(f"Multiple apps found (500): app - {app_id}, country - {country_id}, lang - {lang}")
        else:
            return data['data'][0]


def collect_from_store(store, method, languages=None, countries=None, full_detail=False, params={}, log=print):
    """
    Collect data from Apple or Google store using https://github.com/digitalmethodsinitiative/itunes-app-scraper
    or https://github.com/digitalmethodsinitiative/google-play-scraper

    :param store: 'apple' or 'google'
    :param method: 'app', 'list', 'search', 'developer', 'similar', 'permissions'
    :param params: parameters for the method
    :param log: log function
    """
    dynamic_app_detail_args = {} # TODO Set below for apple store, but unsure if there is a default

    scraper = None
    if store == 'apple':
        scraper = AppStoreScraper()
        # Get parameters according to itunes_app_scraper
        # Still have to map the keyword in /web/src/store/method.ts
        if params.get('collection', None):
            params['collection'] = getattr(AppStoreCollections, params.get('collection'))
        dynamic_app_detail_args = {'add_ratings':True}
    elif store == 'google':
        scraper = PlayStoreScraper()
        if params.get('collection', None):
            params['collection'] = getattr(PlayStoreCollections, params.get('collection'))
    else:
        raise Exception("Unknown store: {}".format(store))

    languages = [lang.strip() for lang in languages] if languages else []
    countries = [country.strip() for country in countries] if countries else []
    result = []
    done = 0

    if method == 'app':
        ids = [id.strip() for id in params.get('appId', '')]

        count = len(ids) * len(languages) * len(countries)

        for id in ids:
            for language in languages:
                for country in countries:
                    values = {
                        'app_id': id,
                        'country': country,
                        'short': params.get('short'),
                    }

                    if store == 'google':
                        values["lang"] = language

                    args = {k: v for k, v in values.items() if v is not None}
                    export_args = {k: v for k, v in args.items() if k not in ("short")}

                    try:
                        app = scraper.get_app_details(**args, **dynamic_app_detail_args)
                        result.append({**export_args, **app})

                        done += 1
                        log(f"Collected {done} of {count} apps")
                        time.sleep(1) # avoid throttling

                    except (PlayStoreException, AppStoreException) as e:
                        # collection cannot be loaded. Probably due to invalid
                        # query, so no error, just assume no result
                        done += 1
                        log(f"Error collecting app {id}: {e}")

        return result

    elif method == 'list':

        count = len(languages) * len(countries)

        for language in languages:
            for country in countries:
                values = {
                    'collection': params.get('collection'),
                    'category': params.get('category'),
                    'age': params.get('age'),
                    'num': params.get('num'),
                    'country': country
                }

                if store == 'google':
                    values['lang'] = language

                args = {k: v for k, v in values.items() if v is not None}
                export_args = {k: v for k, v in args.items() if k not in ("num")}

                try:
                    apps = scraper.get_app_ids_for_collection(**args)

                    if full_detail:
                        apps = scraper.get_multiple_app_details(apps, country=country, **dynamic_app_detail_args)
                    else:
                        apps = [{"id": id} for id in apps]

                    for app in apps:
                        result.append({**export_args, **app})

                    done += 1
                    log(f"Collected {done} of {count} apps")

                except (PlayStoreException, AppStoreException) as e:
                    # collection cannot be loaded. Probably due to invalid
                    # query, so no error, just assume 0 results
                    done += 1
                    log(f"Error collecting collection {params.get('collection')}: {e}")
                    
        return result

    elif method == 'search':
        queries = [query.strip() for query in params.get('queries', [])]

        count = len(queries) * len(languages) * len(countries)

        for query in queries:
            for language in languages:
                for country in countries:
                    values = {
                        'term': query,
                        'num': params.get('num'),
                        'page': params.get('page'),
                        'country': country,
                        'lang': language,
                    }
                    args = {k: v for k, v in values.items() if v is not None}
                    export_args = {k: v for k, v in args.items() if k not in ("num", "page")}

                    try:
                        apps = scraper.get_app_ids_for_query(**args)
                        if full_detail:
                            apps = scraper.get_multiple_app_details(apps, country=country, lang=language, **dynamic_app_detail_args)
                        else:
                            apps = [{"id": id} for id in apps]

                        for app in apps:
                            result.append({**export_args, **app})
                            
                        done += 1
                        log(f"Collected {done} of {count} queries")

                    except (PlayStoreException, AppStoreException) as e:
                        # search results cannot be parsed, probably due to
                        # lack of results, i.e. faulty query or 0 hits
                        done += 1
                        log(f"Error collecting query {query}: {e}")

        return result
    
    elif method == 'developer':
        ids = [id.strip() for id in params.get('devId', [])]

        count = len(ids) * len(languages) * len(countries)

        for id in ids:
            for language in languages:
                for country in countries:
                    values = {
                        'developer_id': id,
                        'country': country,
                    }

                    if store == 'google':
                        values['lang'] = params.get('lang')
                        values['num'] = params.get('num')

                    args = {k: v for k, v in values.items() if v is not None}
                    export_args = {k: v for k, v in args.items() if k not in ("num")}

                    try:
                        apps = scraper.get_app_ids_for_developer(**args)

                        if full_detail:
                            apps = scraper.get_multiple_app_details(apps, country=country, **dynamic_app_detail_args)
                        else:
                            apps = [{"id": id} for id in apps]

                        for app in apps:
                            result.append({**export_args, **app})

                        done += 1
                        log(f"Collected {done} of {count} queries")

                    except (PlayStoreException, AppStoreException) as e:
                        # no apps for developer, probably because of
                        # faulty developer ID or wrong language/country
                        done += 1
                        log(f"Error collecting developer {id}: {e}")

        return result

    elif method == 'similar':
        ids = [id.strip() for id in params.get('appId', [])]

        count = len(ids) * len(languages) * len(countries)

        for id in ids:
            for language in languages:
                for country in countries:
                    values = {
                        'app_id': id,
                        'country': country,
                        'lang': language,
                    }
                    args = {k: v for k, v in values.items() if v is not None}
                    export_args = {k: v for k, v in args.items() if k not in ("app_id")}
                    export_args = {"similar_to": id, **export_args}

                    try:
                        apps = scraper.get_similar_app_ids_for_app(**args)

                        if full_detail:
                            apps = scraper.get_multiple_app_details(apps, country=country, lang=language, **dynamic_app_detail_args)
                        else:
                            apps = [{"id": id} for id in apps]

                        for app in apps:
                            result.append({**export_args, **app})
                            
                        done += 1
                        log(f"Collected {done} of {count} apps")

                    except (PlayStoreException, AppStoreException) as e:
                        # no similar apps, probably because app did not
                        # exist or other parameters were faulty
                        done += 1
                        log(f"Error collecting similar apps for app {id}: {e}")

        return result

    elif method == 'permissions':
        ids = [id.strip() for id in params.get('appId', [])]

        count = len(ids) * len(languages) * len(countries)

        for id in ids:
            for language in languages:
                values = {
                    'app_id': id,
                    'lang': language,
                    'short': params.get('short'),
                }
                args = {k: v for k, v in values.items() if v is not None}
                export_args = {k: v for k, v in args.items() if k not in ("short")}

                try:
                    permissions = scraper.get_permissions_for_app(**args)

                    for permission in permissions:
                        result.append({**export_args, "permission": permission})

                    done += 1
                    log(f"Collected {done} of {count} apps")

                except (PlayStoreException) as e:
                    # no permissions for app, probably because of
                    # faulty app ID or wrong language/country
                    done += 1
                    log(f"Error collecting permissions for app {id}: {e}")

        return result


def convert_screenshot(image_obj, c="w", f="jpeg"):
    """
    Converts Apple's image objects to useable URLs

    :param dict image_obj:  The dict object returned from Apple
    :param str c:           Unknown, but "w" is used in interface
    :param str f:           Image type ("jpeg" and "webp" are known options)
    """
    url = image_obj.get("url", "")
    return url.replace("{w}", str(image_obj.get("width", ""))).replace("{h}", str(image_obj.get("height", ""))).replace(
        "{c}", c).replace("{f}", f)

def camel_to_title(string):
    return  "".join([char if char.islower() else " " + char for char in string]).title()
def case_to_title(string):
    return string.replace('_', ' ').replace('-', ' ').title()