import requests
import ural

from requests.exceptions import RequestException


class WikipediaSearch:
    """
    Wikipedia scraper utility class
    """
    language_map = {
        "af": "Afrikaans",
        "als": "Alemannic German",
        "smn": "Inari Sámi",
        "atj": "Atikamekw",
        "nrm": "Norman",
        "ay": "Aymara",
        "az": "Azerbaijani",
        "cdo": "Eastern Min",
        "mwl": "Mirandese",
        "an": "Aragonese",
        "bar": "Bavarian",
        "cs": "Czech",
        "cbk-zam": "Zamboanga Chavacano",
        "co": "Corsican",
        "dga": "Dagaare",
        "da": "Danish",
        "se": "Northern Sámi",
        "de": "German",
        "dsb": "Lower Sorbian",
        "et": "Estonian",
        "eml": "Emilian–Romagnol",
        "ang": "Old English",
        "en": "English",
        "eu": "Basque",
        "fat": "Fante",
        "hif": "Fiji Hindi",
        "fo": "Faroese",
        "fy": "West Frisian",
        "gag": "Gagauz",
        "gl": "Galician",
        "gpe": "Ghanaian Pidgin English",
        "ext": "Extremaduran",
        "guw": "Gun",
        "gur": "Farefare (Gurene)",
        "haw": "Hawaiian",
        "hsb": "Upper Sorbian",
        "hr": "Croatian",
        "nah": "Nahuatl",
        "is": "Icelandic",
        "jam": "Jamaican Patois",
        "kl": "Greenlandic",
        "csb": "Kashubian",
        "lt": "Lithuanian",
        "li": "Limburgish",
        "ln": "Lingala",
        "olo": "Livvi-Karelian",
        "hu": "Hungarian",
        "pcm": "Nigerian Pidgin",
        "nl": "Dutch",
        "nds-nl": "Dutch Low Saxon",
        "jbo": "Lojban",
        "frr": "North Frisian",
        "pih": "Norfuk",
        "nn": "Norwegian (Nynorsk)",
        "no": "Norwegian (Bokmål)",
        "uz": "Uzbek",
        "om": "Oromo",
        "pfl": "Palatine German",
        "zh-min-nan": "Southern Min",
        "pdc": "Pennsylvania Dutch",
        "hak": "Hakka Chinese",
        "nds": "Low German",
        "pl": "Polish",
        "kaa": "Karakalpak",
        "qu": "Quechua (Southern Quechua)",
        "crh": "Crimean Tatar",
        "rmy": "Romani (Vlax Romani)",
        "sco": "Scots",
        "trv": "Seediq",
        "stq": "Saterland Frisian",
        "simple": "Simple English",
        "sk": "Slovak",
        "sl": "Slovene",
        "szl": "Silesian",
        "so": "Somali",
        "srn": "Sranan Tongo",
        "sh": "Serbo-Croatian",
        "fi": "Finnish",
        "sv": "Swedish",
        "tly": "Talysh",
        "zh": "Chinese (vernacular)",
        "wuu": "Wu Chinese",
        "zh-yue": "Cantonese",
        "gan": "Gan Chinese",
        "tr": "Turkish",
        "tk": "Turkmen",
        "ug": "Uyghur",
        "roa-tara": "Tarantino",
        "gd": "Scottish Gaelic",
        "ik": "Iñupiaq",
        "fj": "Fijian",
        "za": "Zhuang (Standard Zhuang)",
        "chy": "Cheyenne",
        "vep": "Veps",
        "rm": "Romansh",
        "fur": "Friulian",
        "la": "Latin",
        "lfn": "Lingua Franca Nova",
        "ga": "Irish",
        "ltg": "Latgalian",
        "lv": "Latvian",
        "eo": "Esperanto",
        "lad": "Judaeo-Spanish",
        "gn": "Guarani",
        "ca": "Catalan",
        "ty": "Tahitian",
        "fiu-vro": "Võro",
        "frp": "Franco-Provençal",
        "vo": "Volapük",
        "war": "Waray",
        "vls": "West Flemish",
        "cy": "Welsh",
        "tay": "Atayal",
        "nv": "Navajo",
        "sn": "Shona",
        "bm": "Bambara",
        "bew": "Betawi",
        "scn": "Sicilian",
        "mg": "Malagasy",
        "pms": "Piedmontese",
        "gor": "Gorontalo",
        "id": "Indonesian",
        "ms": "Malay",
        "ace": "Acehnese",
        "ban": "Balinese",
        "map-bms": "Banyumasan",
        "jv": "Javanese",
        "su": "Sundanese",
        "bbc": "Toba Batak",
        "mad": "Madurese",
        "ch": "Chamorro",
        "ny": "Chewa",
        "tum": "Tumbuka",
        "dtp": "Dusun",
        "br": "Breton",
        "wa": "Walloon",
        "pt": "Portuguese",
        "es": "Spanish",
        "fr": "French",
        "vec": "Venetian",
        "oc": "Occitan",
        "ff": "Fula",
        "sm": "Samoan",
        "ki": "Kikuyu",
        "ha": "Hausa",
        "to": "Tongan",
        "ig": "Igbo",
        "tet": "Tetum",
        "ia": "Interlingua",
        "ie": "Interlingue",
        "it": "Italian",
        "ro": "Romanian",
        "pcd": "Picard",
        "lmo": "Lombard",
        "sc": "Sardinian",
        "xh": "Xhosa",
        "zu": "Zulu",
        "kg": "Kongo",
        "nia": "Nias",
        "lij": "Ligurian",
        "bi": "Bislama",
        "tpi": "Tok Pisin",
        "mi": "Māori",
        "avk": "Kotava",
        "min": "Minangkabau",
        "ast": "Asturian",
        "bs": "Bosnian",
        "pap": "Papiamento",
        "nap": "Neapolitan",
        "ilo": "Ilocano",
        "ve": "Venda",
        "lb": "Luxembourgish",
        "pag": "Pangasinan",
        "lld": "Ladin",
        "roa-rup": "Aromanian",
        "btm": "Mandailing Batak",
        "st": "Sotho",
        "nso": "Northern Sotho",
        "tn": "Tswana",
        "sq": "Albanian",
        "ss": "Swazi",
        "kab": "Kabyle",
        "din": "Dinka",
        "vi": "Vietnamese",
        "wo": "Wolof",
        "sw": "Swahili",
        "gv": "Manx",
        "pam": "Kapampangan",
        "tl": "Tagalog",
        "nov": "Novial",
        "mt": "Maltese",
        "io": "Ido",
        "kbp": "Kabiye",
        "ku": "Kurdish (Kurmanji)",
        "lg": "Luganda",
        "rw": "Kinyarwanda",
        "rn": "Kirundi",
        "ts": "Tsonga",
        "sg": "Sango",
        "diq": "Zaza",
        "gcr": "French Guianese Creole",
        "fon": "Fon",
        "kw": "Cornish",
        "ht": "Haitian Creole",
        "ceb": "Cebuano",
        "bcl": "Central Bikol",
        "yo": "Yoruba",
        "guc": "Wayuu",
        "bdr": "West Coast Bajau",
        "bjn": "Banjarese",
        "dag": "Dagbani",
        "tw": "Twi",
        "igl": "Igala",
        "pwn": "Paiwan",
        "shi": "Shilha",
        "ee": "Ewe",
        "kus": "Kusaal",
        "ami": "Amis",
        "szy": "Sakizaya",
        "ksh": "Ripuarian",
        "kcg": "Tyap",
        "zea": "Zeelandic",
        "bat-smg": "Samogitian",
        "el": "Greek",
        "pnt": "Pontic Greek",
        "av": "Avar",
        "ady": "Adyghe",
        "kbd": "Kabardian",
        "ab": "Abkhaz",
        "ba": "Bashkir",
        "be": "Belarusian (Narkamaŭka)",
        "be-tarask": "Belarusian (Taraškievica)",
        "bxr": "Buryat (Russia Buriat)",
        "bg": "Bulgarian",
        "sr": "Serbian",
        "tg": "Tajik",
        "inh": "Ingush",
        "os": "Ossetian",
        "kv": "Komi",
        "krc": "Karachay-Balkar",
        "ky": "Kyrgyz",
        "mrj": "Hill Mari",
        "kk": "Kazakh",
        "lbe": "Lak",
        "lez": "Lezgian",
        "mk": "Macedonian",
        "mdf": "Moksha",
        "mn": "Mongolian",
        "ce": "Chechen",
        "mhr": "Meadow Mari",
        "koi": "Komi-Permyak",
        "rue": "Rusyn",
        "ru": "Russian",
        "sah": "Yakut",
        "cu": "Old Church Slavonic",
        "tt": "Tatar",
        "alt": "Southern Altai",
        "tyv": "Tuvan",
        "udm": "Udmurt",
        "uk": "Ukrainian",
        "xal": "Kalmyk Oirat",
        "cv": "Chuvash",
        "myv": "Erzya",
        "xmf": "Mingrelian",
        "ka": "Georgian",
        "hyw": "Western Armenian",
        "hy": "Armenian",
        "he": "Hebrew",
        "yi": "Yiddish",
        "ur": "Urdu",
        "ps": "Pashto",
        "pnb": "Western Punjabi",
        "azb": "South Azerbaijani",
        "skr": "Saraiki",
        "sd": "Sindhi",
        "ks": "Kashmiri",
        "glk": "Gilaki",
        "mzn": "Mazanderani",
        "ar": "Arabic",
        "ary": "Moroccan Arabic",
        "arz": "Egyptian Arabic",
        "fa": "Persian",
        "ckb": "Kurdish (Sorani)",
        "arc": "Aramaic (Syriac)",
        "dv": "Maldivian",
        "nqo": "N'Ko",
        "zgh": "Standard Moroccan Amazigh",
        "am": "Amharic",
        "ti": "Tigrinya",
        "awa": "Awadhi",
        "gom": "Konkani (Goan Konkani)",
        "dty": "Doteli",
        "ne": "Nepali",
        "pi": "Pali",
        "bh": "Bihari (Bhojpuri)",
        "mr": "Marathi",
        "mai": "Maithili",
        "new": "Newar",
        "anp": "Angika",
        "sa": "Sanskrit",
        "hi": "Hindi",
        "as": "Assamese",
        "bn": "Bengali",
        "bpy": "Bishnupriya Manipuri",
        "pa": "Punjabi",
        "gu": "Gujarati",
        "or": "Odia",
        "ta": "Tamil",
        "te": "Telugu",
        "kn": "Kannada",
        "tcy": "Tulu",
        "ml": "Malayalam",
        "si": "Sinhala",
        "mni": "Meitei",
        "th": "Thai",
        "lo": "Lao",
        "bo": "Central Tibetan (Lhasa Tibetan)",
        "dz": "Dzongkha",
        "bug": "Buginese",
        "blk": "Pa'O",
        "my": "Burmese",
        "shn": "Shan",
        "mnw": "Mon",
        "km": "Khmer",
        "sat": "Santali",
        "chr": "Cherokee",
        "iu": "Inuktitut",
        "cr": "Cree",
        "ko": "Korean",
        "ja": "Japanese",
        "got": "Gothic",
        "zh-classical": "Classical Chinese"
    }

    def wiki_request(self, auth="", *args, **kwargs):
        """
        Send a Wikipedia API request

        Does some error handling and authentication scaffolding.

        :param str auth:  Wikipedia API auth key (can be empty)
        :param args:  Positional arguments are passed to `requests.get`
        :param kwargs:  Keyword arguments are passed to `requests.get`
        :return dict:  Parsed JSON response, or `None` if there was an error
        """
        if auth:
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"]["Authorization"] = f"Bearer {auth}"

        try:
            result = requests.get(*args, **kwargs)
            if result.status_code != 200:
                raise ValueError(f"Wikipedia API request failed ({result.status_code})")

            result_json = result.json()

            if "error" in result_json:
                raise ValueError(
                    f"Wikipedia API request failed ({result_json['error'].get('info', result_json['error'])})")

            return result_json

        except (ValueError, RequestException) as e:
            self.dataset.log(f"Encountered an error interfacing with the Wikipedia API ({e})")
            return None

    def normalise_pagenames(self, auth, urls):
        """
        Normalise Wikipedia page names

        Resolves redirects, et cetera, for a list of Wikipedia URLs

        :param str auth:  Wikipedia API auth key (can be empty)
        :param list urls:  List of URLs to normalise
        :return dict:  Dictionary with language codes as keys and a list of
        normalised page names in that language as values
        """
        parsed_urls = {}
        for url in urls:
            domain = ural.get_hostname(url)
            if not domain.endswith("wikipedia.org"):
                self.dataset.log(f"{url} is not a Wikipedia URL, skipping")
                continue

            if domain.startswith("www.") or len(domain.split(".")) == 2:
                language = "en"
            else:
                language = domain.split(".")[0]

            page = url.split("/wiki/")
            if len(page) < 2:
                self.dataset.log(f"{url} is not a Wikipedia URL, skipping")
                continue

            page = page.pop().split("#")[0].split("?")[0]

            if language not in parsed_urls:
                parsed_urls[language] = set()

            parsed_urls[language].add(page)

        self.dataset.update_status(f"Collecting canonical article names for {len(parsed_urls):,} Wikipedia article(s).")

        # sort by language (so we can batch requests)
        result = {}
        for language, pages in parsed_urls.items():
            api_base = f"https://{language}.wikipedia.org/w/api.php"
            pages = list(pages)
            canonical_titles = []

            self.dataset.update_status(
                f"Collecting canonical article names for articles on {language}.wikipedia.org ({self.map_lang(language)})")
            # get canonical title for URL
            while pages:
                batch = pages[:50]
                pages = pages[50:]
                canonical = self.wiki_request(auth, api_base, params={
                    "action": "query",
                    "format": "json",
                    "redirects": "1",
                    "titles": "|".join(batch),
                })

                if not canonical:
                    self.dataset.update_status("Could not get canonical name for article batch - skipping")
                    continue

                for page in canonical["query"]["pages"].values():
                    canonical_titles.append(page["title"])

            result[language] = canonical_titles

        return {lang: result[lang] for lang in result if result[lang]}

    def map_lang(self, code):
        """
        Get full name of a Wikipedia language, if available
        :param str code:  Language code, e.g. `nl`
        :return str:  Language name in English, or the code if unavailable
        """
        return self.language_map.get(code, code)
