"""
Collect Wikipedia tables of content revisions
"""
import json
import ural

from backend.lib.wikipedia_scraper import WikipediaSearch
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput
from common.lib.exceptions import QueryParametersException


class SearchWikiToc(BasicProcessor, WikipediaSearch):
    """
    Collect Wikipedia TOCs
    """
    type = "wikitocs-search"  # job ID
    category = "Search"  # category
    title = "Wikipedia table of content scraper"  # title displayed in UI
    description = "Retrieve Wikipedia TOCs."  # description displayed in UI
    extension = "html"  # extension of result file, used internally and in UI

    # not available as a processor for existing datasets
    accepts = [None]

    template = """
<!DOCTYPE html>
<head>
  <title>Wikipedia Table of Contents browser</title>
  <style>
    h1, h2 { background: #363636; color: white; padding: 0.4em 0.25em 0.25em 0.25em; }
    html { font-family: sans-serif; background: white; color: #363636; }
    a { color: inherit; }
    .meta { padding: 0.5em;
    #toc, .toc, .mw-warning {
      border: 1px solid #aaa;
      background-color: #f9f9f9;
      padding: 5px;
      font-size: 95%;
      font-family: serif;
    }
    #toc ul, .toc ul {
      list-style-type: none;
      list-style-image: none;
      text-align: left;
      padding-left: 1em;
    }
  </style>
  <script src="https://code.jquery.com/jquery-1.12.4.min.js" integrity="sha256-ZosEbRLbNQzLpnKIkEdrPv7lOy9C27hHQ+Xp8a4MxAQ=" crossorigin="anonymous"></script>
  <script src="https://code.jquery.com/ui/1.14.0/jquery-ui.min.js" integrity="sha256-Fb0zP4jE3JHqu+IBB9YktLcSjI1Zc6J2b6gTjB0LpoM=" crossorigin="anonymous"></script>
  <link rel="stylesheet" href="https://code.jquery.com/ui/1.14.0/themes/base/jquery-ui.css">
  <script>
  function showTOC(index) {
    var revision=$("#results").data('revisions').revisions[index];
    /*console.log(revision);*/
    
    if($("#wikitocbrowser").data('rev')!=revision.revid) {
        $("#wikitocbrowser").data('rev',revision.revid); 
        
        
        var toc='<table id="toc" class="toc"><tr><td><div id="toctitle"><h3>Contents</h3></div><ul>';
        
        var revurl='http://'+revision.lang+'.wikipedia.org/wiki/'+$("#results").data('revisions').title+'?oldid='+revision.revid;
        var userurl='http://'+revision.lang+'.wikipedia.org/wiki/User:'+revision.user;
        
        var level=0;
        for(var i=0;i<revision.entries.length;i++) {
            data=revision.entries[i];
            if(data.toclevel>level) {
                toc=toc+'<ul>';
            }
            if(data.toclevel<level) {
                toc=toc+'</li></ul>';
            }
            entry='<li class="toclevel-'+data.toclevel+' tocsection-'+data.index+'">'+
                '<a href="'+revurl+'#'+data.anchor+'">'+
                '<span class="tocnumber">'+data.number+'</span> '+
                '<span class="toctext">'+data.line+'</span></a>';
            if(data.toclevel==level) {
                toc=toc+'</li>';
            }
            toc=toc+entry;
            level=data.toclevel;
        }
        
        toc=toc+"</ul></td></tr></table>";
        
        var revurl='http://'+revision.lang+'.wikipedia.org/wiki/'+$("#results").data('revisions').title+'?oldid='+revision.revid;
        var userurl='http://'+revision.lang+'.wikipedia.org/wiki/User:'+revision.user;
        
        $("#wikitocbrowser div.meta").html(
            '<table>'+
            '<tr><td>Revision</td><td><a href="'+revurl+'">'+revision.revid+'</a> ['+(index+1)+'/'+$("#results").data("revisions").revisions.length+']</td></tr>'+
            '<tr><td>Timestamp</td><td>'+revision.timestamp+'</td></tr>'+
            '<tr><td>User</td><td><a href="'+userurl+'">'+revision.user+'</a></td></tr>'+
            '<tr><td>Comment</td><td>'+revision.comment+'</td></tr>'+
            '</table>'
        );
        $("div.meta table").css('font-size','16px');
        
        $("#wikitocbrowser div.tocview").html(toc);
    }
}

function wikitocInitResult(result) {
    $("#results").data('revisions',result);
    $('#results').css('display','block');
    $('#results').css('width','93%');
    $('#results').css('margin','0 auto');
    $('#results').css('border','none');
    $("#results").empty();
    $("#results").html('<div id="wikitocbrowser"></div>');
    $("#wikitocbrowser").css({'padding':'10px','font-size':'16px'});
    $("#wikitocbrowser").data('rev',-1);
    $("#wikitocbrowser").append('<h1>'+$("#results").data('revisions').title+' ('+$("#results").data('revisions').lang+')</h1>');
    
    links='<div style="margin: 1em auto 1em auto;">permalinks: ';
    
    link='<a href="'+
                  window.location.protocol+'//'+window.location.host+window.location.pathname+
                  '?perm&title='+$("#titleurl").val()+
                  '&lang='+$("select[name='lang']").val()+
                  '&maxrv='+$("input[name='maxrv']").val();
    link=link+'">with updates</a>, ';
    links=links+link;

    link='<a href="'+
                  window.location.protocol+'//'+window.location.host+window.location.pathname+
                  '?perm&title='+$("#titleurl").val()+
                  '&lang='+$("select[name='lang']").val()+
                  '&maxrv='+$("input[name='maxrv']").val();
    link=link+'&last='+$("#results").data('revisions').revisions[0].revid;
    link=link+'">without updates</a>.</div>';
    links=links+link;
    
    //$("#wikitocbrowser").append(links);   //@todo, this has become obsolete

    $("#wikitocbrowser").append('<div id="sliderdec">&lt;</div>');
    $("#wikitocbrowser").append('<div id="slider"></div>');
    $("#wikitocbrowser").append('<div id="sliderinc">&gt;</div>');
    $("#slider").css({'width':'93%','float':'left','margin':'0 10px 0 10px'});
    $("#sliderdec").css({'width':'2%','float':'left','text-align':'center','cursor':'pointer'});
    $("#sliderinc").css({'width':'2%','float':'left','text-align':'center','cursor':'pointer'});
    $("#slider").slider({
        max   : $("#results").data('revisions').revisions.length-1,
        slide : function(event,ui) {
                    /*console.log(ui.value);
                    console.log($("#results").data('revisions').revisions[ui.value]);*/
                    showTOC(ui.value);
                }
    });
    $("#sliderdec").click(function() {
        var value = $("#slider").slider("value");
        if(value>0) {
            $("#slider").slider("value",value-1);
            showTOC(value-1);
        }
        return false;
    });
    $("#sliderinc").click(function() {
        var value = $("#slider").slider("value");
        if(value<$("#slider").slider("option","max")) {
            $("#slider").slider("value",value+1);
            showTOC(value+1);
        }
        return false;
    });

    $("#wikitocbrowser").append('<div class="tocview"></div><div class="meta">');
    $("#wikitocbrowser .tocview").css({'width':'47%','float':'left','margin-top':'1em'});
    $("#wikitocbrowser .meta").css({'width':'47%','float':'right','border':'1px solid black','margin-top':'1em','font-size':'16px'});
    
    $("#results").append('<div style="clear: both;">&nbsp;</div>');
    showTOC(0);
    
}
$(document).ready(function() {
    wikitocInitResult(%%json%%);
});
  </script>
</head>
<body>
<div id="results"></div>
</body>
"""

    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "For a given Wikipedia article URL, retrieve a number of revisions of those pages and extract "
                    "the table of contents from the page. This allows for analysis of a page's evolution through "
                    "observation of the page's sections.\n\n"
                    "Note that not all historical versions of a page may be available; for example, if the page has "
                    "been deleted its contents can no longer be retrieved.\n\n"
                    "Note that te retrieval and parsing of revisions is a **slow** process! Make sure you know what "
                    "you want before you start data collection."
        },
        "urls": {
            "type": UserInput.OPTION_TEXT,
            "help": "Wikipedia URL"
        },
        "rvlimit": {
            "type": UserInput.OPTION_TEXT,
            "help": "Number of revisions",
            "min": 1,
            "max": 500,
            "coerce_type": int,
            "default": 50,
            "tooltip": "Number of revisions to collect per page. Cannot be more than 500. Note that pages may have "
                       "fewer revisions than the upper limit you set."
        },
    }

    def process(self):
        """
        Retrieve TOCs

        todo: this is set up for capturing multiple pages at once, but the UI
        doesn't deal with that yet

        :param dict query:  Search query parameters
        """
        wiki_apikey = self.config.get("api.wikipedia")
        urls = [url.strip() for url in self.parameters.get("urls").split("\n")]
        urls = [url for url in urls if url][0]
        tocs = {}

        for language, pages in self.normalise_pagenames(wiki_apikey, [urls]).items():
            api_base = f"https://{language}.wikipedia.org/w/api.php"
            pages = list(pages)
            tocs[language] = {}

            for page in pages:
                # get most recent revisions to then parse
                revisions = self.wiki_request(wiki_apikey, api_base, params={
                    "action": "query",
                    "format": "json",
                    "prop": "revisions",
                    "rvlimit": self.parameters.get("rvlimit"),
                    "titles": page,
                })

                if not revisions:
                    self.dataset.log(f"Skipping {page} - could not get data from Wikipedia API")
                    continue

                revisions = list(revisions["query"]["pages"].values())[0]["revisions"]
                self.dataset.update_status(
                    f"Collecting {len(revisions):,} revisions for article '{page}' on {language}.wikipedia.org")
                num_parsed = 0

                for revision in revisions:
                    # now get the parsed version of each revision
                    # this is pretty slow, but the only way to get the TOC...
                    content = self.wiki_request(wiki_apikey, api_base, params={
                        "action": "parse",
                        "format": "json",
                        "oldid": revision["revid"],
                        "prop": "sections|revid"
                    })

                    if not content:
                        self.dataset.log(f"Skipping revision {revision['revid']} - could not get data from Wikipedia API")
                        continue

                    num_parsed += 1
                    self.dataset.update_status(
                        f"Collecting {num_parsed:,}/{len(revisions):,} revisions for article '{page}' on {language}.wikipedia.org")
                    self.dataset.update_progress(num_parsed / len(revisions))

                    if page not in tocs[language]:
                        tocs[language][page] = []

                    tocs[language][page].append({
                        **revision,
                        "entries": content["parse"]["sections"]
                    })

        # OK, we have our data, let's render it
        num_results = 0
        embedded_json = ""
        for language, pages in tocs.items():
            for page, revisions in pages.items():
                embedded_json = {
                    "title": page,
                    "lang": language,
                    "revisions": revisions
                }
                num_results += len(revisions)
                break
                # todo: implement multi-page drifting/browsing

        with self.dataset.get_results_path().open("w") as outfile:
            outfile.write(self.template.replace("%%json%%", json.dumps(embedded_json)))

        return self.dataset.finish(num_rows=num_results)

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query

        Will raise a QueryParametersException if invalid parameters are
        encountered. Parameters are additionally sanitised.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        if not query.get("urls").strip():
            raise QueryParametersException("You need to provide a valid Wikipedia URL")

        return {
            "urls": query.get("urls").strip()
        }