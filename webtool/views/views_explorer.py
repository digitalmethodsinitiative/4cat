"""
4CAT Explorer views

The Explorer shows a dataset's items in a legible way and lets people annotate
them. It is not a page of its own: it is a pane on the dataset page, below the
dataset metadata, swapped in by htmx when the 'Explore & Annotate' toggle is
flipped. Everything here therefore renders a partial, not a document.

Annotation *values* are saved one at a time, by the input that changed; the
annotation *fields* they belong to are edited in a form in the dataset metadata
box. In both cases the server is the only party that decides what an annotation
field is - a request says which field and item it means and what the value is,
never what the field looks like.
"""

import collections
import json
import secrets

from flask import Blueprint, current_app, request, render_template, g, redirect, url_for
from flask_login import login_required, current_user

from webtool.lib.helpers import annotation_context, can_annotate_dataset, error, setting_required
from common.lib.annotation import ANNOTATION_TYPES
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, AnnotationException

component = Blueprint("explorer", __name__)
api_ratelimit = current_app.limiter.shared_limit("45 per minute", scope="api")


def explorer_dataset(key: str):
    """
    Load the dataset an Explorer request is about

    Bundles the checks every Explorer endpoint needs, so none of them can
    forget one: the dataset exists, this user may see it, and it is one the
    Explorer can show at all.

    :param str key:  Dataset key
    :return tuple:  `(dataset, None)`, or `(None, response)` with a response to
                    return instead - callers return the second value if it is set
    """
    try:
        dataset = DataSet(key=key, db=g.db, modules=g.modules)
    except DataSetException:
        return None, error(404, error="Dataset not found.")

    if not current_user.can_access_dataset(dataset):
        return None, error(403, error="This dataset is private.")

    if len(dataset.get_genealogy()) > 1:
        return None, error(404, error="The Explorer is only available for top-level datasets.")

    if not dataset.check_dataset_finished():
        return None, error(404, error="This dataset didn't finish executing.")

    return dataset, None


def annotation_field_context(dataset: DataSet) -> dict:
    """
    Context for anything rendering this dataset's annotation fields

    The shared context (see webtool.lib.helpers.annotation_context) plus what
    only the templates in this blueprint need.

    :param DataSet dataset:  Dataset to get the fields of
    :return dict:  Template context
    """
    context = annotation_context(dataset)
    context.update({
        "dataset": dataset,
        "processors": current_app.fourcat_modules.processors,
    })
    return context


def explorer_page_context(dataset: DataSet, page=1, sort="", reverse=False) -> dict:
    """
    Collect one page of dataset items, with their annotations

    :param DataSet dataset:  Dataset to page through
    :param int page:  Page number, 1-indexed
    :param str sort:  Item key to sort on; empty for the dataset's own order
    :param bool reverse:  Whether to sort descending
    :return dict:  Template context, or None if the page holds no items
    """
    items_per_page = g.config.get("explorer.posts_per_page", 50)
    max_items = g.config.get("explorer.max_posts", 500000)
    offset = (int(page) - 1) * items_per_page

    item_ids = []
    items = []

    # the dataset's own order needs no sorting pass, so it can start reading at
    # the offset instead of walking everything before it
    if not sort or (sort == "dataset-order" and not reverse):
        count = offset
        for row in dataset.iterate_items(warn_unmappable=False, get_annotations=False, offset=offset):
            count += 1
            item_ids.append(row["id"])
            items.append(row)
            if count >= (offset + items_per_page) or count > max_items:
                break
    else:
        count = 0
        get_annotations = sort in dataset.get_annotation_field_labels()
        for row in sort_and_iterate_items(dataset, sort, reverse=reverse, warn_unmappable=False,
                                          get_annotations=get_annotations):
            count += 1
            if count <= offset:
                continue
            item_ids.append(row["id"])
            items.append(row)
            if count >= (offset + items_per_page) or count > max_items:
                break

    if not items:
        return None

    # annotations for these items only, keyed by item so the template can find
    # them without searching
    item_annotations = collections.defaultdict(dict)
    if dataset.annotation_fields:
        for annotation in dataset.get_annotations_for_item(item_ids):
            item_annotations[annotation.item_id][annotation.field_id] = annotation

    context = annotation_field_context(dataset)
    context.update({
        "datasource": dataset.parameters.get("datasource"),
        # data source templates hide identifying details for these
        "pseudonymised": bool(dataset.parameters.get("pseudonymise", False)),
        "items": items,
        "media_files": dataset.get_media_from_children(item_ids=item_ids),
        "annotations": item_annotations,
        "page": int(page),
        "offset": offset,
        "items_per_page": items_per_page,
        "item_count": int(dataset.data["num_rows"]),
        "max_items": max_items,
        "sort": sort,
        "reverse": reverse,
    })
    return context


def request_page():
    """
    Page, sort and order as asked for in the query string

    :return tuple:  `(page, sort, reverse)`
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    return page, request.args.get("sort", ""), request.args.get("order") == "reverse"


@component.route("/results/<string:key>/explorer/pane/")
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
def explorer_pane(key: str):
    """
    The Explorer pane for a dataset, as a partial

    Loaded into the dataset page the first time the 'Explore & Annotate' toggle
    is flipped. Holds the controls, the items and the pagination; paging and
    sorting afterwards only replace the latter two.

    :param str key:  Dataset key
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    page, sort, reverse = request_page()
    context = explorer_page_context(dataset, page, sort, reverse)
    if not context:
        return render_template("explorer/empty.html", dataset=dataset)

    return render_template("explorer/pane.html", **context)


@component.route("/results/<string:key>/explorer/items/")
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
def explorer_items(key: str):
    """
    One page of dataset items, as a partial

    Swapped into the pane when paging or sorting. The pagination changes along
    with the items, so it is part of the same partial.

    :param str key:  Dataset key
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    page, sort, reverse = request_page()
    context = explorer_page_context(dataset, page, sort, reverse)
    if not context:
        return render_template("explorer/empty.html", dataset=dataset)

    return render_template("explorer/items.html", **context)


@component.route("/results/<string:key>/explorer/", defaults={"page": 1})
@component.route("/results/<string:key>/explorer/page/<int:page>")
@login_required
def explorer_redirect(key: str, page=1):
    """
    Send the Explorer's old address to its new one

    The Explorer used to be a page of its own; links to it are out in the world
    and in people's bookmarks, so they land on the dataset page with the
    Explorer pane open instead of on a 404.

    :param str key:  Dataset key
    :param int page:  Page number
    """
    return redirect(url_for("dataset.show_result", key=key, view="explore", page=page,
                            sort=request.args.get("sort"), order=request.args.get("order")))


@component.route("/results/<string:key>/explorer/annotation/", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
def save_annotation(key: str):
    """
    Save a single annotation

    One annotation per request: the input that changed posts itself. Only the
    value is taken from the request - what the annotation *is* (its label, type
    and options) is read from the dataset's own annotation fields, and who made
    it from the session. A request can therefore not invent a field, annotate a
    dataset it may not see, or attribute an annotation to someone else.

    :param str key:  Dataset key

    :return-error 400:  If the field is unknown or the request is incomplete
    :return-error 403:  If this user may not annotate this dataset
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    if not can_annotate_dataset(dataset):
        return error(403, error="You cannot annotate this dataset.")

    field_id = request.form.get("field_id")
    item_id = request.form.get("item_id")
    if not field_id or not item_id:
        return error(400, error="An annotation needs a field_id and an item_id.")

    field = dataset.annotation_fields.get(field_id)
    if not field:
        return error(400, error="Unknown annotation field.")

    if field.get("from_dataset"):
        return error(403, error="Processor-generated annotations cannot be edited.")

    # a checkbox field posts one value per checked option and nothing at all
    # when everything is unchecked, which is a valid (empty) annotation
    if field["type"] == "checkbox":
        value = request.form.getlist("value")
    else:
        value = request.form.get("value", "")

    try:
        dataset.save_annotations([{
            "field_id": field_id,
            "item_id": item_id,
            "label": field["label"],
            "type": field["type"],
            "options": ",".join(field.get("options", {}).values()),
            "value": value,
            "author": current_user.get_id(),
            "by_processor": False,
        }])
    except AnnotationException as e:
        return error(400, error=str(e))

    return "", 204, {"HX-Trigger": json.dumps({"annotation-saved": {"field_id": field_id, "item_id": item_id}})}


@component.route("/results/<string:key>/explorer/annotation-fields/")
@api_ratelimit
@login_required
@setting_required("privileges.can_use_explorer")
def annotation_fields_editor(key: str):
    """
    The annotation field editor, as a partial

    Fetched the first time the annotation fields box in the dataset metadata is
    expanded.

    :param str key:  Dataset key
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    context = annotation_field_context(dataset)
    context["can_annotate"] = can_annotate_dataset(dataset)
    return render_template("explorer/annotation-fields-editor.html", **context)


@component.route("/results/<string:key>/explorer/annotation-fields/new/")
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
def new_annotation_field(key: str):
    """
    An empty annotation field row, as a partial

    Appended to the editor's list when someone adds a field. The row is
    rendered by the same template the saved ones are, so there is one
    definition of what a field row looks like; its ID is minted here rather
    than in the browser, so IDs only ever come from one place.

    :param str key:  Dataset key
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    if not can_annotate_dataset(dataset):
        return error(403, error="You cannot annotate this dataset.")

    return render_template("explorer/annotation-field.html", dataset=dataset,
                           field_id=secrets.token_hex(8), field={"type": "text", "label": ""},
                           from_datasets={}, processors=current_app.fourcat_modules.processors,
                           can_annotate=True, is_new=True)


@component.route("/results/<string:key>/explorer/annotation-fields/", methods=["POST"])
@api_ratelimit
@login_required
@setting_required("privileges.can_run_processors")
@setting_required("privileges.can_use_explorer")
def save_annotation_fields(key: str):
    """
    Save the annotation fields of a dataset

    The form posts the fields it was given, in the order they are shown. Fields
    the editor never sees - processor-generated ones hidden in the Explorer -
    are merged back in here by ID, rather than by treating everything absent as
    deleted.

    Deleting a field or changing its type deletes the annotations that belong
    to it. Only the server knows how many that is, so the first request comes
    back with a confirmation listing the damage; the second carries `confirm`.

    :param str key:  Dataset key

    :return-error 400:  If the fields are not valid
    :return-error 403:  If this user may not annotate this dataset
    """
    dataset, denied = explorer_dataset(key)
    if denied:
        return denied

    if not can_annotate_dataset(dataset):
        return error(403, error="You cannot annotate this dataset.")

    old_fields = dataset.annotation_fields
    try:
        new_fields = parse_annotation_field_form(request.form, old_fields)
    except AnnotationException as e:
        context = annotation_field_context(dataset)
        context.update({"can_annotate": True, "warning": str(e)})
        return render_template("explorer/annotation-fields-editor.html", **context), 400

    # keep the fields the editor never got to see
    for field_id, field in old_fields.items():
        if field.get("hide_in_explorer"):
            new_fields[field_id] = field

    if not request.form.get("confirm"):
        impact = annotation_field_impact(dataset, old_fields, new_fields)
        if impact:
            # asked in a popup rather than in place of the editor, so saying no
            # leaves the editor exactly as it was; the request came from the
            # editor, so the response has to say where it really belongs
            return render_template("explorer/annotation-fields-confirm.html", dataset=dataset,
                                   impact=impact, form=request.form), 200, {
                                       "HX-Retarget": "#popup-host",
                                       "HX-Reswap": "innerHTML"}

    try:
        dataset.save_annotation_fields(new_fields)
    except AnnotationException as e:
        context = annotation_field_context(dataset)
        context.update({"can_annotate": True, "warning": str(e)})
        return render_template("explorer/annotation-fields-editor.html", **context), 400

    # the editor comes back re-rendered; the summary in the metadata box and the
    # items' annotation inputs are swapped out of band, since both now show
    # something else
    context = annotation_field_context(dataset)
    context["can_annotate"] = True
    context["saved"] = True
    return render_template("explorer/annotation-fields-saved.html", **context)


def parse_annotation_field_form(form, old_fields: dict) -> dict:
    """
    Rebuild the annotation fields from the editor's form

    The form is flat - `label-<field_id>`, `type-<field_id>`, and one
    `option-<field_id>` per choice - with `field-order` listing the field IDs in
    the order they are shown, which is the order they are saved in.

    Processor-generated fields are read back from the fields already saved: only
    their label is editable, so nothing else the form says about them is used.

    :param form:  The submitted form (`request.form`)
    :param dict old_fields:  The dataset's current annotation fields
    :return dict:  Annotation fields, ready for `save_annotation_fields()`
    """
    new_fields = {}

    for field_id in form.getlist("field-order"):
        label = form.get("label-%s" % field_id, "").strip()
        if not label:
            raise AnnotationException("Annotation fields must have a label.")

        old_field = old_fields.get(field_id, {})
        if old_field.get("from_dataset"):
            # only the label can be changed on these
            field = {**old_field, "label": label}
        else:
            field_type = form.get("type-%s" % field_id, "text")
            if field_type not in ANNOTATION_TYPES:
                raise AnnotationException("'%s' is not a valid annotation field type." % field_type)

            field = {"type": field_type, "label": label}

            if field_type in ("dropdown", "checkbox"):
                options = [option.strip() for option in form.getlist("option-%s" % field_id) if option.strip()]
                if not options:
                    raise AnnotationException("Choice fields need at least one option (%s)." % label)
                if len(options) != len(set(options)):
                    raise AnnotationException("Options must be unique (%s)." % label)
                # options keep the IDs they had, so existing annotations keep
                # pointing at the same option; new ones get an ID that cannot
                # collide with one already in use
                old_options = {v: k for k, v in old_field.get("options", {}).items()}
                field["options"] = {
                    old_options.get(option, secrets.token_hex(4)): option
                    for option in options
                }

        new_fields[field_id] = field

    labels = [field["label"] for field in new_fields.values()]
    if len(labels) != len(set(labels)):
        raise AnnotationException("Annotation field labels must be unique.")

    return new_fields


def annotation_field_impact(dataset: DataSet, old_fields: dict, new_fields: dict) -> list:
    """
    What saving these annotation fields would destroy

    Deleting a field deletes its annotations; so does changing a field between
    kinds, since the old values cannot be read as the new type. This counts
    what that would come to, so the confirmation can say it out loud.

    :param DataSet dataset:  Dataset the fields belong to
    :param dict old_fields:  Fields as currently saved
    :param dict new_fields:  Fields as they would be saved
    :return list:  One dict per affected field, empty if nothing is lost
    """
    text_types = ("text", "textarea")
    choice_types = ("dropdown", "checkbox")

    # counted in the database rather than by reading every annotation of the
    # dataset into memory, which on a thoroughly annotated one is a lot of rows
    # to load in order to end up with a handful of numbers
    counts = collections.Counter({
        row["field_id"]: row["count"] for row in
        g.db.fetchall("SELECT field_id, COUNT(*) AS count FROM annotations WHERE dataset = %s GROUP BY field_id",
                      (dataset.key,))
    })

    impact = []
    for field_id, old_field in old_fields.items():
        if not counts[field_id]:
            continue

        if field_id not in new_fields:
            reason = "deleted"
        else:
            old_type = old_field.get("type")
            new_type = new_fields[field_id].get("type")
            # text to choice, choice to text, and one choice kind to another all
            # leave the existing values unreadable
            changed = old_type != new_type and (
                (old_type in text_types and new_type in choice_types)
                or (old_type in choice_types and new_type in text_types)
                or (old_type in choice_types and new_type in choice_types)
            )
            if not changed:
                continue
            reason = "changed from %s to %s" % (old_type, new_type)

        impact.append({"label": old_field.get("label", field_id), "reason": reason, "annotations": counts[field_id]})

    return impact


def sort_and_iterate_items(dataset: DataSet, sort="", reverse=False, **kwargs):
    """
    Loop through both csv and NDJSON files.
    Wrapper function for `dataset.sort_and_iterate_items()`.

    :param dataset:				The dataset object.
    :param sort:				The item key that determines the sort order.
    :param reverse:				Whether to sort by largest values first.

    :returns dict:				Yields iterated items
    """

    # Resort to regular iteration if the dataset is larger than the maximum
    # allowed items for the Explorer.
    if dataset.data["num_rows"] > g.config.get("explorer.max_posts", 500000):
        yield from dataset.iterate_items(**kwargs)
        return

    # Use dataset's sort_and_iterate_items function which can accept chunk_size and
    # creates a sorted temporary file (thus not using so much memory).
    yield from dataset.sort_and_iterate_items(sort=sort, reverse=reverse, **kwargs)
