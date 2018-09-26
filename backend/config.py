class config:
    """
    Scraper configuration
    """

    """
    Postgres login details
    """
    db_user = "fourcat"
    db_name = "fourcat"
    db_password = "mosselm4n"

    """
    These probably need some benchmarking!
    """
    max_thread_scrapers = 10
    max_board_scrapers = 2

    """
    Logs will be saved here - rotated by appended numbers
    """
    log_path = "4cat-scraper.log"
    image_path = "images"
