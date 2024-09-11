"""
Selenium Webpage HTML Scraper

Currently designed around Firefox, but can also work with Chrome; results may vary
"""
import datetime
import time
from urllib.parse import unquote, urlparse, parse_qs

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common.config_manager import config
from extensions.web_studies.selenium_scraper import SeleniumSearch
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException
from common.lib.helpers import validate_url
from common.lib.item_mapping import MappedItem
from common.lib.user_input import UserInput

class AmazonProductSearch(SeleniumSearch):
    """
    Get HTML via the Selenium webdriver and Firefox browser
    """
    type = "amazon_products-search"  # job ID
    extension = "ndjson"

    # Known carousels to collect recommendations
    # All carousels will be collected, but only these will but used to columns (via map_item) and as depth crawl options
    # {column_name: known_carousel_name}
    known_carousels = {
        "also_bought": "Customers who bought this item also bought",
        "also_viewed": "Customers who viewed this also viewed",
        "related_products": "Products related to this item",
        "browsing_history_viewed": "Customers who viewed items in your browsing history also viewed",
        "bought_after_viewing": "What do customers buy after viewing this item?",
        "similar_ship_close": "Similar items that ship from close to you",
        "all_recs": "All Recommendations", # SPECIAL type used to crawl all recommendations
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        options = {
            "intro-1": {
                "type": UserInput.OPTION_INFO,
                "help": "Collect related products from Amazon by providing a list of Amazon product URLs. This will "
                        "collect product details as well as recommended related products such as 'Customers who bouth "
                        "this item also bought' and 'What do customers buy after viewing this item?'."
            },
            "query-info": {
                "type": UserInput.OPTION_INFO,
                "help": "Please enter a list of Amazon product urls one per line."
            },
            "query": {
                "type": UserInput.OPTION_TEXT_LARGE,
                "help": "List of urls"
            },
            "depth": {
                "type": UserInput.OPTION_TEXT,
                "help": "Recommendation depth.",
                "min": 0,
                "max": 3,
                "default": 0,
                "tooltip": "0 only collects products from provided links; otherwise collect additional products from recommended links selected below."
            },
            "rec_type": {
                "type": UserInput.OPTION_MULTI_SELECT,
                "help": "Recommended products to collect.",
                "options": AmazonProductSearch.known_carousels,
                "default": [],
                "tooltip": "Select the types of recommended products to additionally collect. If none are selected, only the provided urls will be collected. If \"All Recommendations\" is selected, all recommended products will be collected regardless of other selections."
            },
        }

        return options

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on image sets

        :param module: Module to determine compatibility with
        """
        return config.get('selenium.installed', False, user=user)

    def get_items(self, query):
        """
        Separate and check urls, then loop through each and collects the HTML.

        :param query:
        :return:
        """
        self.dataset.log('Query: %s' % str(query))
        depth = query.get('depth', 0)
        subpage_types = query.get('rec_type', [])
        urls_to_collect = [{"url": AmazonProductSearch.normalize_amazon_links(url), 'current_depth': 0} for url in query.get('urls')]

        # Do not scrape the same page twice
        collected_urls = set()
        num_urls = len(urls_to_collect)
        urls_collected = 0
        missing_carousels = 0

        while urls_to_collect:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while scraping urls from the Web Archive")
                # Get the next URL to collect

            url_obj = urls_to_collect.pop(0)
            url = url_obj['url']
            current_depth = url_obj['current_depth']

            self.dataset.update_progress(collected_urls / num_urls) # annoyingly a moving target but not sure how to truly estimated it
            if depth == 0:
                self.dataset.update_status("%i of %i URLs collected" % (urls_collected, num_urls))
            else:
                self.dataset.update_status("Collecting depth %i of %i (%i of %i URLs collected)" % (current_depth + 1, depth + 1, urls_collected, num_urls))

            try:
                asin_id = AmazonProductSearch.extract_asin_from_url(url)
            except ValueError:
                self.dataset.log("Unable to identify Amazon product ID (ASIN) for %s; is this a proper Amazon link?" % url)
                asin_id = None

            result = {
                "url": url,
                "final_url": None,
                "product_id": asin_id,
                "title": None,
                "subtitle": None,
                "byline": None,
                "num_reviews": None,
                "rating": None,
                "badges": None,
                "thumbnail": None,
                "body": None,
                "html": None,
                "recommendations": {},
                "detected_404": None,
                "timestamp": None,
                "error": '',
            }

            # Get the URL
            success, errors = self.get_with_error_handling(url, max_attempts=2)

            # Collection timestamp
            result['timestamp'] = int(datetime.datetime.now().timestamp())
            collected_urls.add(url)

            # Check for 404 or other errors
            detected_404 = self.check_for_404()
            if detected_404:
                result['error'] += self.driver.title.lower() + "\n"
                success = False
            if not success:
                self.dataset.log(f"Failed to collect {url}: {errors}")
                result['error'] += errors
                result['detected_404'] = detected_404
                yield result
                continue

            # Success; collect the final URL and load full page
            result["final_url"] = self.driver.current_url
            self.scroll_down_page_to_load(max_time=5)

            # Collect the product details
            # These may change or not exist, but I would prefer to still collect them here if possible as we lose access to selenium later
            # We can attempt to update them from the source via map_item later (e.g., if None, check the html)
            title = self.driver.find_elements(By.XPATH, "//span[contains(@id, 'productTitle')]")
            if title:
                result['title'] = title[0].text
            subtitle = self.driver.find_elements(By.XPATH, "//span[contains(@id, 'productSubtitle')]")
            if subtitle:
                result['subtitle'] = subtitle[0].text
            byline = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'bylineInfo')]")
            if byline:
                result["byline"] = byline[0].text
            num_reviews = self.driver.find_elements(By.XPATH, "//a[contains(@id, 'acrCustomerReviewLink')]")
            if num_reviews:
                result["num_reviews"] = num_reviews[0].text
            rating = self.driver.find_elements(By.XPATH, "//span[contains(@id, 'acrPopover')]")
            if rating:
                result["rating"] = rating[0].text
            # badges
            badges = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'zg-badge-wrapper')]")
            if badges:
                result["badges"] = badges[0].text
            # image
            image_containers = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'imageBlock_feature_div')]")
            if image_containers:
                for thumb in image_containers[0].find_elements(By.XPATH, ".//img"):
                    if thumb.get_attribute("class") == "a-lazy-loaded":
                        # Ignore the lazy loaded image
                        continue
                    result["thumbnail"] = thumb.get_attribute("src")
                    break

            # Collect the HTML and extract text
            result['html'] = self.driver.page_source
            result['body'] = self.scrape_beautiful_text(result['html'])

            # Collect recommendations
            carousels = self.driver.find_elements(By.CSS_SELECTOR, "div[class*=a-carousel-container]")
            found_carousels = 0
            for carousel in carousels:
                heading = carousel.find_elements(By.XPATH, ".//h2[contains(@class, 'a-carousel-heading')]")
                if not heading:
                    # Not a recommendation carousel
                    continue
                # self.dataset.log("Found carousel: %s" % heading[0].text)
                # self.dataset.log("Carousel: %s" % carousel.get_attribute("innerHTML"))
                # self.dataset.log("Carousel: %s" % carousel.text)

                found_carousels += 1
                heading_text = heading[0].text
                result["recommendations"][heading_text] = []

                # Collect page numbers
                current = carousel.find_element(By.XPATH, ".//span[contains(@class, 'a-carousel-page-current')]")
                final = carousel.find_element(By.XPATH, ".//span[contains(@class, 'a-carousel-page-max')]")
                current = int(current.text) if current.text else 1
                final = int(final.text) if final.text else 1

                while current <= final:
                    recs = carousel.find_elements(By.TAG_NAME, "li")
                    for rec in recs:
                        rec_link = rec.find_elements(By.CSS_SELECTOR, "a[class*=a-link-normal]")
                        if rec_link:
                            rec_link = rec_link[0].get_attribute("href")
                            # TODO: do we wish to extract recommendation details? Will be impossible unless we save the new HTML that exists after the next page
                            # if rec.find_elements(By.XPATH, ".//span/div/div/div/*"):
                            #     print(rec.find_elements(By.XPATH, ".//span/div/div/div/*")[0].text)
                            result["recommendations"][heading_text].append(AmazonProductSearch.normalize_amazon_links(rec_link))
                        else:
                            # blank rec; likely all recs have been collected
                            continue

                    # Check if there is a next page and click if so
                    next_button = carousel.find_elements(By.XPATH, ".//div[contains(@class, 'a-carousel-right')]")
                    if next_button and current < final:
                        next_button[0].find_element(By.XPATH, ".//span[contains(@class, 'a-button-inner')]").click()
                        WebDriverWait(carousel, 10).until(EC.text_to_be_present_in_element(
                            (By.XPATH, ".//span[contains(@class, 'a-carousel-page-current')]"), str(current + 1)))
                        # even with the Wait for page to update, the actual recs may take a bit longer
                        time.sleep(.5)

                    current += 1

            if found_carousels == 0:
                # No carousels found, but some were present
                result['error'] += "No recommendations found\n"
                if len(carousels) > 0:
                    # Carousels were present, but none were recommendations... possible issue w/ carousel detection
                    missing_carousels += 1

            if depth > 0 and result["recommendations"] and current_depth < depth:
                # Collect additional subpages
                additional_subpages = []
                if "all_recs" in subpage_types:
                    # Collect all types
                    for rec_links in result["recommendations"].values():
                        additional_subpages += rec_links
                else:
                    for rec_type in subpage_types:
                        full_rec_type = AmazonProductSearch.known_carousels.get(rec_type, None)
                        if full_rec_type in result["recommendations"]:
                            additional_subpages += result["recommendations"][full_rec_type]

                # Remove duplicates
                additional_subpages = list(set(additional_subpages))
                num_urls += len(additional_subpages)
                self.dataset.update_status(f"Adding {len(additional_subpages)} additional subpages to collect")
                urls_to_collect += [{'url': url, 'current_depth': current_depth + 1} for url in additional_subpages if url not in collected_urls]

            urls_collected += 1
            yield result

        if missing_carousels > 0:
            self.log.warning("Amazon product collector: No recommendations found on %i of %i urls" % (missing_carousels, num_urls))


    @staticmethod
    def map_item(page_result):
        """
        Map the item to the expected format for 4CAT

        :param json page_result:  Object with original datatypes
        :return dict:  Dictionary in the format expected by 4CAT
        """
        # Convert the recommendations to comma-separated strings
        recommendations = page_result.pop("recommendations")
        page_result["rec_types_displayed"] = ", ".join(recommendations.keys())
        page_result["all_recs"] = ", ".join([rec for rec_list in recommendations.values() for rec in rec_list])
        for column_name, rec_type in AmazonProductSearch.known_carousels.items():
            if column_name == "all_recs":
                # Ignore special type for all recommendations
                continue
            page_result[column_name] = ", ".join(recommendations.get(rec_type, []))

        # Remove the HTML; maybe should only do for frontend...
        page_result.pop("html")

        # Convert the body to a single string
        page_result["body"] = "\n".join(page_result["body"])

        return MappedItem(page_result)


    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the Selenium Webpage Scraper.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """

        # this is the bare minimum, else we can't narrow down the full data set
        if not query.get("query", None):
            raise QueryParametersException("Please provide a List of urls.")
        urls = [url.strip() for url in query.get("query", "").replace("\n", ",").split(',')]
        preprocessed_urls = [url for url in urls if validate_url(url)]
        if not preprocessed_urls:
            raise QueryParametersException("No Urls detected!")

        return {
            "urls": preprocessed_urls,
            "depth": query.get("depth", 0),
            "rec_type": query.get("rec_type", [])
            }

    @staticmethod
    def normalize_amazon_links(link):
        """
        Helper to remove reference information from Amazon links to standardize and ensure we do not re-collect the same
        product across different links.
        """
        link = unquote(link)
        if 'https://www.amazon.com/sspa/click?' in link:
            # Special link; remove the click reference
            parsed_url = urlparse(link)
            normal_path = parse_qs(parsed_url.query).get("url", [""])[0]
            parsed_url = parsed_url._replace(query="", path=normal_path)
        else:
            parsed_url = urlparse(link)

        parsed_url = parsed_url._replace(query="")
        path = parsed_url.path

        if "/dp/" in path:
            asin = path.split("/dp/")[1].split("/")[0]
        else:
            # Not a product link; return the original
            return link
        parsed_url = parsed_url._replace(path=f"/dp/{asin}/")

        return parsed_url.geturl()

    @staticmethod
    def extract_asin_from_url(link):
        """
        Helper to remove reference information from Amazon links to create networks
        """
        link = unquote(link)
        if "/dp/" not in link:
            raise ValueError("Unable to identify Amazon product ID (ASIN)")
        return link.split("/dp/")[1].split("/")[0]