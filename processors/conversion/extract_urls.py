"""
Extract URLs from columns

Optionally expand shortened URLs (from Stijn's expand_url_shorteners)
"""
import csv
import re
import time
import requests
from ural import urls_from_text

from common.lib.exceptions import ProcessorInterruptedException
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Stijn Peeters", "Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ExtractURLs(BasicProcessor):
    """
    Retain only posts where a given column matches a given value
    """
    type = "extract-urls-filter"  # job type ID
    category = "Conversion"  # category
    title = "Extract URLs (and optionally expand)"  # title displayed in UI
    description = "Extract any URLs from selected column(s) and, optionally, expand any shortened URLs. This will create" \
                  " a new dataset."
    extension = "csv"

    options = {
        "columns": {
            "type": UserInput.OPTION_TEXT,
            "help": "Columns to extract URLs",
            "default": "body",
            "inline": True,
            "tooltip": "If column contains a single URL, use that URL; else, try to find image URLs in the column's content",
        },
        "correct_croudtangle": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "CroudTangle dataset",
            "tooltip": "CroudTangle text contains resolved links using :=: symbols; these are extracted directly",
        },
        "expand_urls": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Expand shortened URLs",
            "tooltip": "This can take a long time for large datasets and it is NOT recommended to run this processor on datasets larger than 10,000 items.",
        },
        "return_matches_only": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Only return rows with URLs",
            "tooltip": "If selected, only rows with URLs are added to the new dataset, else all rows are retained",
        },
        "split-comma": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Split column values by comma?",
            "default": True,
            "tooltip": "If enabled, columns can contain multiple URLs separated by commas, which will be considered "
                   "separately"
        },
    }

    # taken from https://github.com/timleland/url-shorteners
    # current as of 9 April 2021
    redirect_domains = (
        "t.ly", "0rz.tw", "1-url.net", "1link.in", "1tk.us", "1un.fr", "1url.com", "1url.cz", "1wb2.net", "2.gp",
        "2.ht",
        "2ad.in", "2big.at", "2doc.net", "2fear.com", "2long.cc", "2no.co", "2pl.us", "2tu.us", "2ty.in", "2u.xf.cz",
        "2ya.com", "3.ly", "3ra.be", "3x.si", "4i.ae", "4ms.me", "4sq.com", "4url.cc", "4view.me", "5em.cz", "5url.net",
        "5z8.info", "6fr.ru", "6g6.eu", "6url.com", "7.ly", "7fth.cc", "7li.in", "7vd.cn", "8u.cz", "23o.net", "76.gd",
        "77.ai", "98.to", "126.am", "307.to", "944.la", "a0.fr", "a2a.me", "a.co", "a.gg", "a.nf", "aa.cx", "abbr.sk",
        "abbrr.com", "abcurl.net", "ad5.eu", "ad7.biz", "ad-med.cz", "ad.vu", "adb.ug", "adf.ly", "adfa.st", "adfly.fr",
        "adfoc.us", "adjix.com", "adli.pw", "admy.link", "adv.li", "afx.cc", "ajn.me", "aka.gr", "al.ly", "alil.in",
        "alturl.com", "any.gs", "apne.ws", "aqva.pl", "ar.gy", "ares.tl", "arst.ch", "asso.in", "atu.ca", "au.ms",
        "ayt.fr",
        "azali.fr", "azc.cc", "b00.fr", "b2l.me", "b23.ru", "b54.in", "bacn.me", "baid.us", "bc.vc", "bcool.bz",
        "bee4.biz",
        "bim.im", "binged.it", "bit.do", "bit.ly", "bitly.ws", "bitw.in", "bizj.us", "bkite.com", "blap.net", "ble.pl",
        "blip.tv", "bloat.me", "bnc.lt", "boi.re", "bote.me", "bougn.at", "br4.in", "bravo.ly", "bre.is", "brk.to",
        "brzu.net", "bsa.ly", "budurl.com", "buff.ly", "buk.me", "bul.lu", "burnurl.com", "bxl.me", "bzh.me", "c-o.in",
        "cachor.ro", "canurl.com", "captur.in", "catchylink.com", "cbs.so", "cbug.cc", "cc.cc", "ccj.im", "cf2.me",
        "cf6.co", "cf.ly", "chilp.it", "chl.li,", "chzb.gr", "cjb.net", "cl.lk", "cl.ly", "clck.ru", "cleanuri.com",
        "cli.gs", "cliccami.info", "clickmeter.com", "clickmetertracking.com", "clickthru.ca", "clikk.in", "clop.in",
        "cmpdnt.cc", "cn86.org", "cnhv.co", "coinurl.com", "conta.cc", "cort.as", "cot.ag", "couic.fr", "cr.tl",
        "crks.me",
        "ctvr.us", "cudder.it", "cur.lv", "curl.im", "cut.ci", "cut.pe", "cut.sk", "cutt.eu", "cutt.ly", "cutt.us",
        "cutu.me", "cuturl.com", "cybr.fr", "cyonix.to", "d75.eu", "daa.pl", "dai.ly", "dd.ma", "ddp.net",
        "decenturl.com",
        "dfl8.me", "dft.ba", "digbig.com", "disq.us", "dld.bz", "dlvr.it", "do.my", "doiop.com", "dolp.cc",
        "dopen.us", "dopice.sk", "droid.ws", "dv.gd", "dwarfurl.com", "dy.fi", "dyo.gs", "e37.eu", "easyuri.com",
        "easyurl.net", "ecra.se", "eepurl.com", "ely.re", "erax.cz", "erw.cz", "esyurl.com", "eweri.com", "ewerl.com",
        "ex9.co", "ezurl.cc", "fa.b", "fa.by", "fav.me", "fbshare.me", "ff.im", "fff.re", "fff.to", "fff.wf",
        "fhurl.com",
        "filz.fr", "fire.to", "firsturl.de", "firsturl.net", "flic.kr", "flq.us", "fly2.ws", "fnk.es", "foe.hn",
        "folu.me",
        "fon.gs", "freak.to", "freze.it", "from.ubs", "fur.ly", "fuseurl.com", "fuzzy.to", "fwd4.me", "fwib.net",
        "g00.me",
        "g2g.to", "g.ro.lt", "gg.gg", "git.io", "gizmo.do", "gl.am", "go2.me", "go2cut.com", "go.9nl.com", "go.ign.com",
        "go.usa.gov", "goo.gl", "goo.lu", "good.ly", "goog.le", "goshrink.com", "gotrim.me", "gowat.ch", "grabify.link",
        "grem.io", "gri.ms", "guiama.is", "gurl.es", "hadej.co", "hec.su", "hellotxt.com", "hex.io", "hide.my",
        "hiderefer.com", "hjkl.fr", "hmm.ph", "hops.me", "hover.com", "href.in", "href.li", "hsblinks.com", "ht.ly",
        "httpslink.com", "htxt.it", "huff.to", "hugeurl.com", "hulu.com", "hurl.it", "hurl.me", "hurl.ws", "i99.cz",
        "i-2.co", "ibit.ly", "icanhaz.com", "icit.fr", "ick.li", "icks.ro", "idek.net", "iiiii.in", "iky.fr", "ilix.in",
        "info.ms", "inreply.to", "is.gd", "iscool.net", "isra.li", "isra.liiterasi.net", "itm.im", "its.my", "ity.im",
        "ix.lt", "ix.sk", "j.gs", "j.mp", "jdem.cz", "jieb.be", "jijr.com", "jmp2.net", "jp22.net", "jpeg.ly", "jqw.de",
        "just.as", "kask.us", "kd2.org", "kfd.pl", "kissa.be", "kl.am", "klck.me", "korta.nu", "kr3w.de", "krat.si",
        "kratsi.cz", "krod.cz", "krunchd.com", "kuc.cz", "kxb.me", "l9.fr", "l9k.net", "l-k.be", "l.gg", "lat.ms",
        "lc-s.co", "lc.cx", "lcut.in", "letop10.", "lety.io", "libero.it", "lick.my", "lien.li", "lien.pl",
        "lifehac.kr",
        "liip.to", "liltext.com", "lin.cr", "lin.io", "linkbee.com", "linkbun.ch", "linkn.co", "liurl.cn", "llu.ch",
        "ln-s.net", "ln-s.ru", "lnk.co", "lnk.gd", "lnk.in", "lnk.ly", "lnk.ms", "lnk.sk", "lnkd.in", "lnked.in",
        "lnki.nl",
        "lnkiy.com,", "lnks.fr", "lnkurl.com", "lnky.fr", "lnp.sn", "loopt.us", "lp25.fr", "lru.jp", "lt.tl", "lurl.no",
        "lvvk.com", "lynk.my", "m1p.fr", "m3mi.com", "macte.ch", "make.my", "mash.to", "mcaf.ee", "mdl29.net",
        "merky.de",
        "metamark.net", "mic.fr", "migre.me", "minilien.com", "miniurl.com", "minu.me", "minurl.fr", "mke.me",
        "moby.to",
        "moourl.com", "more.sh", "mrte.ch", "mut.lu", "myloc.me", "myurl.in", "myurl.in", "n9.cl", "n.pr", "nbc.co",
        "nblo.gs", "ne1.net", "net46.net", "net.ms", "nicou.ch", "nig.gr", "njx.me", "nn.nf", "not.my", "notlong.com",
        "nov.io", "nq.st", "nsfw.in", "nutshellurl.com", "nxy.in", "nyti.ms", "o-x.fr", "oc1.us", "okok.fr", "om.ly",
        "omf.gd", "omoikane.net", "on.cnn.com", "on.mktw.net", "onforb.es", "orz.se", "ou.af", "ou.gd", "oua.be",
        "ouo.io",
        "ow.ly", "p.pw", "para.pt", "parky.tv", "past.is", "pd.am", "pdh.co", "ph.dog", "ph.ly", "pic.gd", "pich.in",
        "pin.st", "ping.fm", "piurl.com", "pli.gs", "plots.fr", "pm.wu.cz", "pnt.me", "po.st", "politi.co", "poprl.com",
        "post.ly", "posted.at", "pp.gg", "ppfr.it", "ppst.me", "ppt.cc", "ppt.li", "prejit.cz", "profile.to", "ptab.it",
        "ptiturl.com", "ptm.ro", "pub.vitrue.com", "pw2.ro", "py6.ru", "q.gs", "qbn.ru", "qicute.com", "qlnk.net",
        "qqc.co",
        "qr.net", "qrtag.fr", "qte.me", "qu.tc", "quip-art.com", "qxp.cz", "qxp.sk", "qy.fi", "r.im", "rb6.co",
        "rb6.me",
        "rb.gy", "rcknr.io", "rdz.me", "read.bi", "readthis.ca", "reallytinyurl.com", "rebrand.ly",
        "rebrandlydomain.com",
        "redir.ec", "redir.fr", "redirects.ca", "redirx.com", "redu.it", "ref.so", "reise.lc", "rel.ink", "relink.fr",
        "retwt.me", "ri.ms", "rickroll.it", "riz.cz", "riz.gd", "rod.gs", "roflc.at", "rsmonkey.com", "rt.nu", "rt.se",
        "rt.tc", "ru.ly", "rubyurl.com", "rurl.org", "rww.tw", "s4c.in", "s7y.us", "s-url.fr", "s.id", "safe.mn",
        "sagyap.tk", "sameurl.com", "sdu.sk", "sdut.us", "seeme.at", "segue.se", "sh.st", "shar.as", "shar.es",
        "sharein.com", "sharetabs.com", "shink.de", "shorl.com", "short.cc", "short.ie", "short.nr", "short.pk",
        "short.to",
        "shorte.st", "shortlinks.co.uk", "shortna.me", "shorturl.com", "shoturl.us", "shout.to", "show.my",
        "shrinkee.com",
        "shrinkify.com", "shrinkr.com", "shrinkster.com", "shrinkurl.in", "shrt.fr", "shrt.in", "shrt.st", "shrtco.de",
        "shrten.com", "shrunkin.com", "shw.me", "shy.si", "sicax.net", "simurl.com", "sina.lt", "sk.gy", "skr.sk",
        "skroc.pl", "slate.me", "smallr.com", "smll.co", "smsh.me", "smurl.name", "sn.im", "sn.vc", "snipr.com",
        "snipurl.com", "snsw.us", "snurl.com", "soo.gd", "sp2.ro", "spedr.com", "spn.sr", "sptfy.com", "sq6.ru",
        "sqrl.it",
        "srnk.net", "srs.li", "ssl.gs", "starturl.com", "sturly.com", "su.pr", "surl.co.uk", "surl.hu", "surl.me",
        "sux.cz",
        "sy.pe", "t2m.io", "t.cn", "t.co", "t.lh.com", "ta.gd", "tabzi.com", "tau.pe", "tbd.ly", "tcrn.ch", "tdjt.cz",
        "tgr.me", "tgr.ph", "thesa.us", "thinfi.com", "thrdl.es", "tighturl.com", "tin.li", "tini.cc", "tiniuri.com",
        "tiny123.com", "tiny.cc", "tiny.lt", "tiny.ly", "tiny.ms", "tiny.pl", "tinyarro.ws", "tinylink.in", "tinytw.it",
        "tinyuri.ca", "tinyurl.com", "tinyurl.hu", "tinyvid.io", "tixsu.com", "tk.", "tl.gd", "tldr.sk", "tldrify.com",
        "tllg.net", "tmi.me", "tnij.org", "tnij.org", "tnw.to", "tny.com", "tny.cz", "tny.im", "to8.cc", "to.ly",
        "togoto.us", "tohle.de", "totc.us", "toysr.us", "tpm.ly", "tpmr.com", "tr5.in", "tr.im", "tr.my", "tra.kz",
        "traceurl.com", "trck.me", "trick.ly", "trkr.ws", "trunc.it", "turo.us", "tweetburner.com", "twet.fr",
        "twhub.com",
        "twi.im", "twirl.at", "twit.ac", "twitclicks.com", "twitterpan.com", "twitterurl.net", "twitterurl.org",
        "twitthis.com", "twiturl.de", "twlr.me", "twurl.cc", "twurl.nl", "u6e.de", "u76.org", "u.mavrev.com", "u.nu",
        "u.to", "ub0.cc", "uby.es", "ucam.me", "ug.cz", "ulmt.in", "ulu.lu", "unlc.us", "updating.me", "upzat.com",
        "ur1.ca", "url2.fr", "url4.eu", "url5.org", "url360.me", "url.az", "url.co.uk", "url.ie", "urlao.com",
        "urlborg.com", "urlbrief.com", "urlcover.com", "urlcut.com", "urlenco.de", "urlhawk.com", "urli.nl", "urlin.it",
        "urlkiss.com", "urlkr.com", "urlot.com", "urlpire.com", "urls.fr", "urls.im",
        "urlshorteningservicefortwitter.com",
        "urlx.ie", "urlx.org", "urlz.fr", "urlz.host", "urlzen.com", "urub.us", "usat.ly", "use.my", "utfg.sk", "v5.gd",
        "v.gd", "v.ht", "vaaa.fr", "valv.im", "vaza.me", "vb.ly", "vbly.us", "vd55.com", "verd.in", "vgn.am", "vgn.me",
        "viid.me", "virl.com", "vl.am", "vm.lc", "vov.li", "vsll.eu", "vt802.us", "vur.me", "vv.vg", "w1p.fr",
        "w3t.org",
        "w55.de", "waa.ai", "wapo.st", "wapurl.co.uk", "wb1.eu", "wclink.co", "web99.eu", "wed.li", "wideo.fr",
        "wipi.es",
        "wow.link", "wp.me", "wtc.la", "wu.cz", "ww7.fr", "wwy.me", "x2c.eu", "x2c.eumx", "x10.mx", "x.co", "x.nu",
        "x.se",
        "x.vu", "xaddr.com", "xav.cc", "xeeurl.com", "xgd.in", "xib.me", "xl8.eu", "xoe.cz", "xq.ms", "xr.com",
        "xrl.in",
        "xrl.us", "xt3.me", "xua.me", "xub.me", "xurl.es", "xurl.jp", "xurls.co", "xzb.cc", "y2u.be", "y.ahoo.it",
        "yagoa.fr", "yagoa.me", "yatuc.com", "yau.sh", "ye.pe", "yeca.eu", "yect.com", "yep.it", "yep.it", "yfrog.com",
        "yhoo.it", "yiyd.com", "yogh.me", "yon.ir", "youfap.me", "ysear.ch", "yuarel.com", "yweb.com", "yyv.co",
        "z0p.de",
        "z9.fr", "zapit.nu", "zeek.ir", "zi.ma", "zi.mu", "zi.pe", "zip.net", "zipmyurl.com", "zkr.cz", "zkrat.me",
        "zkrt.cz", "zoodl.com", "zpag.es", "zsms.net", "zti.me", "zubb.it", "zud.me", "zurl.io", "zurl.ws", "zws.im",
        "zxq.net", "zyva.org", "zz.gd", "zzang.kr", "zzb.bz", "›.ws", "✩.ws", "✿.ws", "❥.ws", "➔.ws", "➞.ws", "➡.ws",
        "➨.ws", "➯.ws", "➹.ws", "➽.ws",

        # additions by 4CAT
        "api.parler.com", "trib.al", "fb.watch",
    )

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        All processor on CSV and NDJSON datasets
        """
        return module.get_extension() in ["csv", "ndjson"]

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update "columns" option with parent dataset columns
        """
        options = cls.options
        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["options"] = {v: v for v in columns}
            options["columns"]["default"] = "body" if "body" in columns else sorted(columns,
                                                                                    key=lambda k: "text" in k).pop()

        return options

    def process(self):
        """
        Extract URLs and optionally excand them from URL shorteners

        Replaces redirect URLs on a best-effort basis. Redirects with a status
        code outside the 200-399 range are ignored.
        """
        self.dataset.update_status("Searching for URLs")

        # Get match column parameters
        columns = self.parameters.get("columns", [])
        if type(columns) == str:
            columns = [columns]
        expand_urls = self.parameters.get("expand_urls", False)
        return_matches_only = self.parameters.get("return_matches_only", True)
        correct_croudtangle = self.parameters.get("correct_croudtangle", False)

        # Create fieldnames
        fieldnames = self.source_dataset.get_item_keys(self) + ["4CAT_number_unique_urls", "4CAT_extracted_urls"] + ["4CAT_extracted_from_" + column for column in columns]

        # Avoid requesting the same URL multiple times
        cache = {}

        # write a new file with the updated links
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            processed_items = 0
            url_matches_found = 0
            total_items = self.source_dataset.num_rows
            progress_interval_size = max(int(total_items / 10), 1)  # 1/10 of total number of records
            for item in self.source_dataset.iterate_items(self):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while iterating through items")

                row = item.copy()
                row["4CAT_extracted_urls"] = set()

                for column in columns:
                    value = item.get(column)
                    if not value:
                        continue
                    if type(value) != str:
                        self.dataset.update_status(f"Column \"{column}\" is not text and will be ignored.")
                        # Remove from future
                        columns.remove(column)
                        continue

                    # Check for links
                    identified_urls = self.identify_links(value, self.parameters.get("split-comma", True))
                    if correct_croudtangle:
                        identified_urls = ["".join(id_url.split(":=:")[1:]) if ":=:" in id_url else id_url for id_url in identified_urls]

                    # Expand url shorteners
                    if expand_urls:
                        identified_urls = [self.resolve_redirect(url=url, redirect_domains=self.redirect_domains, cache=cache) for url in identified_urls]

                    # Add identified links
                    row["4CAT_extracted_from_"+column] = identified_urls
                    row["4CAT_extracted_urls"] |= set(identified_urls)

                if (return_matches_only and row["4CAT_extracted_urls"]) or not return_matches_only:
                    row["4CAT_number_unique_urls"] = len(row["4CAT_extracted_urls"])
                    # Edit list/sets
                    for column in fieldnames:
                        if column in row.keys() and type(row[column]) in [list, set]:
                            row[column] = ','.join(row[column])
                    writer.writerow(row)
                    url_matches_found += 1

                processed_items += 1
                if processed_items % progress_interval_size == 0:
                    self.dataset.update_status(f"Processed {processed_items}/{total_items} items; {url_matches_found} items with url(s)")
                    self.dataset.update_progress(processed_items / total_items)
        if cache:
            self.dataset.log(f"Expanded {len(cache)} URLs in dataset")
        self.dataset.finish(url_matches_found)

    @staticmethod
    def resolve_redirect(url, redirect_domains=None, cache={}, depth=0):
        """
        Attempt to resolve redirects

        :param str url: URL to check for redirect
        :param tuple redirect_domains: Tuple with all domains to check for redirects
        :param dict cache: URL cache updated with original cache[original_url] = redirect_url
        :param int depth: Number of redirects to attempt to follow
        :return str: Original url or new url for redirects
        """
        # Can use regex.sub() instead of string
        if hasattr(url, "group"):
            url = url.group(0)

        # get host name to compare to list of shorteners
        host_name = re.sub(r"^[a-z]*://", "", url).split("/")[0].lower()

        if depth >= 10:
            return url

        elif url in cache:
            return cache[url]

        elif redirect_domains is None:
            # No redirect_domains passed; check for redirect!
            pass

        elif "api.parler.com/l" not in url and host_name not in redirect_domains:
            # skip non-redirects
            return url


        # to avoid infinite recursion, do not go deeper than 5 loops and
        # keep track of current depth here:
        depth += 1

        # do this explicitly because it is a known issue and will save
        # one request
        if host_name == "t.co" and "http://" in url:
            url = url.replace("http://", "https://")

        try:
            time.sleep(0.1)
            head_request = requests.head(url, timeout=5)
        except (requests.RequestException, ConnectionError, ValueError, TimeoutError) as e:
            return url

        # if the returned page's status code is in the 'valid request'
        # range, and if it has a Location header different from the page's
        # url, recursively resolve the page it redirects to up to a given
        # depth - infinite recursion is prevented by using a cache
        if 200 <= head_request.status_code < 400:
            redirected_to = head_request.headers.get("Location", url)
            if redirected_to != url:
                cache[url] = redirected_to
                return ExtractURLs.resolve_redirect(redirected_to, redirect_domains, cache, depth)

        return url

    @staticmethod
    def identify_links(text, split_comma=True):
        """
        Search string of text for URLs that may contain links.

        :param str text:            string that may contain URLs
        :param bool split_comma:    if True text will be split by commas
        :return list:  	            list of identified URLs
        """
        if split_comma:
            texts = text.split(",")
        else:
            texts = [text]

        # Extracting all links
        urls = set()
        for string in texts:
            urls |= set([url for url in urls_from_text(string)])
        return list(urls)
