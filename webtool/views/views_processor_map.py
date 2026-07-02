"""
Processor catalogue page (proof of concept).

A thin, unlinked template endpoint that renders the catalogue. It holds no query
logic of its own -- the page fetches everything from the JSON API in
`api_processor_map`. Keeping the presentation here and the data there means this
layer can be restyled, server-rendered, or replaced by a reactive frontend
without touching the API.
"""
from flask import Blueprint, render_template
from flask_login import login_required

component = Blueprint("processormapview", __name__)


@component.route("/processor-catalogue")
@component.route("/processor-catalogue/<processor_type>")
@login_required
def processor_catalogue_page(processor_type=None):
    """Render the processor catalogue: browse/search, then "how to run this".

    With a processor type in the path, the page opens with that processor's detail
    already loaded, so a direct link lands on it instead of the visitor having to
    find and click it. The type is passed through to the client, which validates it
    against the catalogue -- an unknown type just falls back to the browse view.
    """
    return render_template("processor-catalogue.html", processor_type=processor_type)
