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
@login_required
def processor_catalogue_page():
    """Render the processor catalogue: browse/search, then "how to run this"."""
    return render_template("processor-catalogue.html")
