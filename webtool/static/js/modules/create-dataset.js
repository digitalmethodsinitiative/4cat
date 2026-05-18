import {applyProgress, FileReaderPromise, find_parent, getRelativeURL} from "./util.js";
import {popup} from "./popup.js";
import {ui_helpers} from "./ui-helpers.js";
import {multichoice} from "./multichoice.js";

/**
 * Query queueing and updating
 */
export const query = {
    dot_ticker: 0,
    poll_interval: null,
    query_key: null,

    /**
     * Set up query status checkers and event listeners
     */
    init: function () {
        // Check status of query
        if ($('body.result-page').length > 0) {
            query.update_status();
            setInterval(query.update_status, 1500);

            // Check processor queue
            query.check_processor_queue();
            setInterval(query.check_processor_queue, 10000);
        }

        // Check search queue
        if ($('#query-form').length > 0) {
            query.check_search_queue();
            setInterval(query.check_search_queue, 10000);
        }

        //regularly check for unfinished datasets
        setInterval(query.check_resultpage, 1000);

        // Start querying when go button is clicked
        $('#query-form').on('submit', function (e) {
            e.preventDefault();
            query.start();
        });

        // Data source select boxes trigger an update of the boards available for the chosen data source
        $('#datasource-select').on('change', query.update_form);
        $('#datasource-select').trigger('change');

        // Special cases in dataset entry form
        $('#datasource-form').on('change', 'input[type=date]', query.proxy_dates);
        $('#datasource-form').on('change', '#forminput-search_scope', query.handle_density);
        $('#datasource-form').on('change', '#forminput-board', query.custom_board_options);

        // dataset label edit
        $('.result-page .card h2.editable').each(query.label.init);
        $(document).on('click', '.edit-dataset-label', query.label.handle);
        $(document).on('keydown', '#new-dataset-label', query.label.handle);

        $(document).on('click', '.result-page .card .annotation-fields-list .property-badge', query.annotation_label.handle);

        // convert dataset
        $(document).on('change', '#convert-dataset', query.convert_dataset);

        // dataset ownership
        $(document).on('click', '#add-dataset-owner', query.add_owner);
        $(document).on('click', '.remove-dataset-owner', query.remove_owner);
    },

    /**
     * Enable query form, so settings may be changed
     */
    enable_form: function (reset=false) {
        if(reset) {
            $('#query-status .delete-link').remove();
            $('#query-status .status_message .dots').html('');
            $('#query-status .message').html('Enter dataset parameters to begin.');
            $('#query-form .datasource-extra-input').remove();
        }
        $('#query-form fieldset').prop('disabled', false);
        $('#query-status').removeClass('active');
    },

    reset_form: function() {
        query.enable_form(true);
    },

    /**
     * Disable query form, while query is active
     */
    disable_form: function () {
        $('#query-form fieldset').prop('disabled', true);
        $('#query-status').addClass('active');
    },

    /**
     * Tool window: start a query, submit it to the backend
     */
    start: async function (extra_data = null, for_real = false) {
        //check form input
        if (!query.validate()) {
            return;
        }

        // Show loader
        query.check_search_queue();
        query.enable_form();

        let form = $('#query-form');
        let formdata = new FormData(form[0]);

        if (!for_real) {
            // just for validation
            // limit file upload size
            let newFormData = new FormData();
            let snippet_size = 128 * 1024; // 128K ought to be enough for everybody
            for (let pair of formdata.entries()) {
                if (pair[1] instanceof File) {
                    if (!['application/zip', 'application/x-zip-compressed'].includes(pair[1].type)) {
                        const sample_size = Math.min(pair[1].size, snippet_size);
                        const blob = pair[1].slice(0, sample_size); // do not load whole file into memory

                        // make sure we're submitting utf-8 - read and then re-encode to be sure
                        const blobAsText = await FileReaderPromise(blob);
                        const snippet = new File([new TextEncoder().encode(blobAsText)], pair[1].name);
                        newFormData.append(pair[0], snippet);
                    } else {
                        // if this is a zip file, don't bother with a snippet (which won't be
                        // useful) but do send a list of files in the zip
                        const reader = new zip.ZipReader(new zip.BlobReader(pair[1]));
                        const entries = await reader.getEntries();
                        newFormData.append(pair[0] + '-entries', JSON.stringify(
                           entries.map(function(e) {
                               return {
                                   filename: e.filename,
                                   filesize: e.compressedSize
                               };
                           })
                        ));
                        newFormData.append(pair[0], null);
                    }
                } else {
                    newFormData.append(pair[0], pair[1]);
                }
            }
            formdata = newFormData;
        }

        if (extra_data) {
            for (let key in extra_data) {
                formdata.set(key, extra_data[key]);
            }
        }

        // Cache cacheable values
        let datasource = form.attr('class');
        form.find('.cacheable input').each(function () {
            let item_name = datasource + '.' + $(this).attr('name');
            let s = localStorage.setItem(item_name, $(this).val());
        });

        // Disable form
        $('html,body').scrollTop(200);
        query.disable_form();

        // AJAX the query to the server
        // first just to validate - then for real (if validated)
        if (!for_real) {
            $('#query-status .message').html('Validating dataset parameters (do not close your browser)');
        } else {
            $('#query-status .message').html('Starting data collection (do not close your browser)');
        }

        fetch(form.attr('action'), {method: 'POST', body: formdata})
            .then(function (response) {
                return response.json();
            })
            .then(function (response) {
                if (response['status'] === 'error') {
                    query.reset_form();
                    popup.alert(response['message'], 'Error');
                } else if (response['status'] === 'confirm') {
                    query.enable_form();
                    popup.confirm(response['message'], 'Confirm', function () {
                        // re-send, but this time for real
                        query.start({'frontend-confirm': true}, true);
                    });
                } else if (response['status'] === 'validated') {
                    // parameters OK, start for real
                    query.start({'frontend-confirm': true, ...response['keep']}, true);
                } else if (response['status'] === 'extra-form') {
                    // new form elements to fill in
                    // some fancy css juggling to make it obvious that these need to be completed
                    query.enable_form();
                    $('#query-status .message').html('Enter dataset parameters to continue.');
                    let target_top = $('#datasource-form')[0].offsetTop + $('#datasource-form')[0].offsetHeight - 50;

                    let extra_elements = $(response['html']);
                    extra_elements.addClass('datasource-extra-input').css('visibility', 'hidden').css('position', 'absolute').css('display', 'block').appendTo('#datasource-form');
                    let targetHeight = extra_elements.height();
                    extra_elements.css('position', '').css('display', '').css('visibility', '').css('height', 0);

                    $('html,body').animate({scrollTop: target_top + 'px'}, 500, false, function () {
                        extra_elements.animate({'height': targetHeight}, 250, function () {
                            $(this).css('height', '').addClass('flash-once');
                        });
                    });
                } else {
                    $('#query-status .message').html('Query submitted, waiting for results');
                    query.query_key = response['key'];
                    query.check(query.query_key);

                    $('#query-status').append($('<button class="delete-link" data-dataset-key="' + query.query_key + '">Cancel</button>'));

                    // poll results every 2000 ms after submitting
                    query.poll_interval = setInterval(function () {
                        query.check(query.query_key);
                    }, 4000);
                }
            })
            .catch(function (e) {
                query.enable_form();
                popup.alert('4CAT could not process your dataset.', 'Error');
            });
    },

    /**
     * After starting query, periodically check its status and link to result when available
     * @param query_key  Key of started query
     */
    check: function (query_key) {
        /*
        Polls server to check whether there's a result for query
        */
        $.getJSON({
            url: getRelativeURL('api/check-query/'),
            data: {key: query_key},
            success: function (json) {
                query.check_search_queue();

                let status_box = $('#query-status .message');
                let current_status = status_box.html();

                if (json.status !== current_status && json.status_html !== "") {
                    status_box.html(json.status_html);
                }

                if (json.done) {
                    clearInterval(query.poll_interval);
                    applyProgress($('#query-status'), 100);
                    let keyword = json.label;

                    $('#query-results').append('<li><a href="../results/' + json.key + '/">' + keyword + ' (' + json.rows + ' items)</a></li>');
                    query.reset_form();
                    popup.alert('Query for \'' + keyword + '\' complete!', 'Success');
                } else {
                    let dots = '';
                    for (let i = 0; i < query.dot_ticker; i += 1) {
                        dots += '.';
                    }
                    $('#query-status .dots').html(dots);

                    applyProgress($('#query-status'), json.progress);

                    query.dot_ticker += 1;
                    if (query.dot_ticker > 3) {
                        query.dot_ticker = 0;
                    }
                }
            },
            error: function () {
                console.log('Something went wrong while checking query status');
            }
        });
    },

    check_resultpage: function () {
        if (!document.hasFocus()) {
            //don't hammer the server while user is looking at something else
            return;
        }

        let unfinished = $('.dataset-unfinished');
        if (unfinished.length === 0) {
            return;
        }

        $('.dataset-unfinished').each(function () {
            let container = $(this);
            let block_type = container.hasClass('full-block') ? 'full' : 'status';
            $.getJSON({
                url: getRelativeURL('api/check-query/'),
                data: {
                    key: $(this).attr('data-dataset-key'),
                    block: block_type
                },
                success: function (json) {
                    if (json.done) {
                        //refresh
                        window.location = window.location;
                        return;
                    }

                    let status_field = container.find('.dataset-status .result-status');
                    let current_status = status_field.html();
                    applyProgress(status_field, json.progress);
                    if (current_status !== json.status_html) {
                        status_field.html(json.status_html);
                    }
                }
            });
        });
    },

    /**
     * Fancy live-updating child dataset status
     *
     * Checks if running subqueries have finished, updates their status, and re-enabled further
     * analyses if all subqueries have finished
     */
    update_status: function () {
        if (!document.hasFocus()) {
            //don't hammer the server while user is looking at something else
            return;
        }

        // first selector is top-level child datasets (always visible)
        // second selector is children of children (only visible when expanded)
        let queued = $('.top-level > .child-wrapper.running, div[aria-expanded=true] > ol > li.child-wrapper.running');
        if (queued.length === 0) {
            return;
        }

        let keys = [];
        queued.each(function () {
            keys.push($(this).attr('data-dataset-key'));
        });

        $.get({
            url: getRelativeURL('api/check-processors/'),
            data: {subqueries: JSON.stringify(keys)},
            success: function (json) {
                json.forEach(child => {
                    let target = $('body #child-' + child.key);
                    let update = $(child.html);
                    update.attr('aria-expanded', target.attr('aria-expanded'));

                    if (target.attr('data-status') === update.attr('data-status') && target.attr('class') === update.attr('class')) {
                        return;
                    }

                    $('#dataset-results').html(child.resultrow_html);

                    target.replaceWith(update);
                    ui_helpers.conditional_form.init();
                    update.addClass('updated');
                    target.remove();

                    if (child.finished && child.annotation_fields && Object.keys(child.annotation_fields).length > 0) {
                        query.update_annotation_fields_list(child.annotation_fields);
                    }
                });
            }
        });
    },

    update_annotation_fields_list: function (annotation_fields) {
        /**
         * Hot-update the annotation-fields-list section when annotation fields change
         */
        let annotation_list = $('.annotation-fields-list');

        if (annotation_list.length === 0) {
            // Section does not exist yet; find the dataset details card and insert after
            // the last existing fullwidth div before API Credentials or Processors sections
            let card_dl = $('.result-page .card dl');
            if (card_dl.length > 0) {
                let html = '<div class="fullwidth annotation-fields-list"><dt>Annotations</dt><dd><ul>';
                for (let field_id in annotation_fields) {
                    let label = annotation_fields[field_id].label;
                    html += '<li><span class="property-badge" data-annotation-id="' + field_id + '"><i class="fa-solid fa-tag"></i> ' + label + '</span></li>';
                }
                html += '</ul></dd></div>';
                card_dl.find('#dataset-result').before(html);
            }
        } else {
            // Update existing section: add any new fields
            let ul = annotation_list.find('ul');
            for (let field_id in annotation_fields) {
                if (ul.find('[data-annotation-id="' + field_id + '"]').length === 0) {
                    let label = annotation_fields[field_id].label;
                    ul.append('<li><span class="property-badge" data-annotation-id="' + field_id + '"><i class="fa-solid fa-tag"></i> ' + label + '</span></li>');
                }
            }
        }
    },

    check_search_queue: function () {
        /*
        Polls server to check how many search queries are still in the queue
        */
        if (!document.hasFocus()) {
            //don't hammer the server while user is looking at something else
            return;
        }

        $.getJSON({
            url: getRelativeURL('api/check-search-queue/'),
            success: function (json) {

                // Update the query status box with the queue status
                let search_queue_box = $('#search-queue-status .search-queue-message');
                let search_queue_list = $('#search-queue-status .search-queue-list');

                // To display in the search queue box
                let search_queue_length = 0;
                let search_queue_notice = "";

                for (let i = 0; i < json.length; i += 1) {
                    search_queue_length += json[i]['count'];
                    search_queue_notice += " <span class='property-badge'>" + json[i]['processor_name'] + ' (' + json[i]['count'] + ')' + '</span>';
                }

                if (search_queue_length == 0) {
                    search_queue_box.html('Search queue is empty.');
                    search_queue_list.html('');
                } else if (search_queue_length == 1) {
                    search_queue_box.html('Currently collecting 1 dataset: ');
                    search_queue_list.html(search_queue_notice);
                } else {
                    search_queue_box.html('Currently collecting ' + search_queue_length + ' datasets: ');
                    search_queue_list.html(search_queue_notice);
                }
            },
            error: function () {
                console.log('Something went wrong when checking search query queue');
            }
        });
    },

    check_processor_queue: function () {
        /*
        Checks what processors are in the queue and keeps updating the option/run buttons
        and already-queued processes buttons.
        */
        if (!document.hasFocus()) {
            //don't hammer the server while user is looking at something else
            return;
        }

        $.getJSON({
            url: getRelativeURL('api/status.json'),
            success: function (json) {

                // Remove previous notices
                $(".queue-notice").html("");

                const queued_processes = json["items"]["backend"]["queued"];

                // Loop through all running processors
                for (const queued_process in queued_processes) {

                    // The message to display
                    let notice = json["items"]["backend"]["queued"][queued_process] + " in queue";

                    // Add notice if this processor has a run/options button
                    let processor_run = $('.processor-queue-button.' + queued_process + '-button');
                    if ($(processor_run).length > 0) {
                        $('.processor-queue-button.' + queued_process + '-button > .queue-notice').html(notice);
                    }

                    // Add another notice to "analysis results" section if processor is pending
                    let processor_started = $('.processor-result-indicator.' + queued_process + '-button');
                    if ($(processor_started).length > 0) {

                        $('.processor-result-indicator.' + queued_process + '-button.queued-button > .button-object > .queue-notice').html(notice);
                    }
                }
            },
            error: function (error) {
                console.log('Something went wrong when checking 4CAT\'s status');
            }
        });
    },

    /**
     * Validate query submission form
     *
     * @returns {boolean}  Whether the form is ready for submission
     */
    validate: function () {
        /*
        Checks validity of input; this is just a preliminary check, further checks are
        done server-side.
        */

        let valid = true;

        // Country flag check
        if ($('#check-country-flag').is(':checked') && ($('#body-input').val()).length < 2 && valid) {

            let common_countries = ['US', 'GB', 'CA', 'AU'];
            let country = $('#country_flag').val();

            // Don't allow querying without date ranges for the common countries
            if (common_countries.includes(country)) {
                let min_date = $('#option-daterange-min').val();
                let max_date = $('#option-daterange-max').val();

                // Max three monhts for the common country flags without any body parameters
                if (max_date - min_date > 7889231) {
                    valid = false;
                    popup.alert('The date selected is more than three months. Select a date range of max. three months and try again. Only the most common country flags on 4chan/pol/ (US, UK, Canada, Australia) have a date restriction.', 'Error');
                } else {
                    valid = false;
                    $('#input-min-time').focus().select();
                    popup.alert('The most common country flags on 4chan/pol/ (US, Canada, Australia) have a date restriction when you want to retreive all of their posts. Select a date range of max. three months and try again.', 'Error');
                }
            }
        }

        // Return true if everyting is passed
        return valid;
    },

    /**
     * Query form for chosen datasource
     */
    update_form: function () {
        const datasource = $('#datasource-select').val();
        $.get({
            'url': getRelativeURL('api/datasource-form/' + datasource + '/'),
            'success': function (data) {
                $('#query-form-script').remove();
                $('#query-form').removeClass();
                $('#query-form').addClass(datasource);
                $('#datasource-form').html(data.html);

                //automatically fill in cached parameters
                $('#datasource-form .cacheable input').each(function () {
                    let item_name = datasource + '.' + $(this).attr('name');
                    let cached_value = localStorage.getItem(item_name);
                    if (typeof cached_value != 'undefined' && cached_value !== 'undefined') {
                        $(this).val(cached_value);
                    }
                });

                //update data source type indicator
                $('#datasource-type-label').html(data.type.join(", "));

                // update data overview link
                $('.data-overview-link > a').attr("href", getRelativeURL('data-overview/' + data.datasource));

                query.handle_density();
                query.custom_board_options();

                // Render custom multiple choice fields
                // should also be rendered dynamically if processor options are expanded.
                if ($('.multichoice-wrapper').length || $('.multi-select-wrapper').length) {
                    multichoice.makeMultichoice();
                    multichoice.makeMultiSelect();
                }

                ui_helpers.conditional_form.manage(document.getElementById('query-form'));
            },
            'error': function () {
                $('#datasource-select').parents('form').trigger('reset');
                popup.alert('Invalid datasource selected.', 'Error');
            }
        });
    },

    handle_density: function () {
        // datasources may offer 'dense thread' options
        // these are sufficiently generalised that they can be handled in this
        // main script...
        let scope = $('#query-form #forminput-search_scope').val();

        let dense_toggle = (scope === 'dense-threads');
        $('#query-form #forminput-scope_density').prop('disabled', !dense_toggle);
        $('#query-form #forminput-scope_density').parent().parent().toggle(dense_toggle);
        $('#query-form #forminput-scope_length').prop('disabled', !dense_toggle);
        $('#query-form #forminput-scope_length').parent().parent().toggle(dense_toggle);

        let ids_toggle = (scope === 'match-ids');
        $('#query-form #forminput-valid_ids').prop('disabled', !ids_toggle);
        $('#query-form #forminput-valid_ids').parent().parent().toggle(ids_toggle);
    },

    custom_board_options: function () {
        // Some boards/subforums for datasources could have differing options.
        // Use this function to update these dynamically.
        // Board-specific fields can be added with `board_specific` in the datasource's Python configuration.

        let board = $('#forminput-board').val();
        let board_specific = '.form-element[data-board-specific]';

        if ($('.form-element[data-board-specific]').length > 0) {
            $(board_specific).hide();
            $(board_specific + ' input').val(null);
            $(board_specific + ' input').prop('checked', false);
            $(board_specific + ' .multi-select-selected').empty();
            $(board_specific).prop('disabled', true);
            $('.form-element[data-board-specific*="' + board + '"]').prop('disabled', false);
            $('.form-element[data-board-specific*="' + board + '"]').show();
        }

        // there is one data source where the anonymisation and labeling
        // controls are of no use...
        if($('#query-form').hasClass('import_4cat')) {
            $('.dataset-anonymisation').hide();
            $('.dataset-labeling').hide();
        } else {
            $('.dataset-anonymisation').show();
            $('.dataset-labeling').show();
        }
    },

    proxy_dates: function () {
        // convert date to unix timestamp
        // should this be done server-side instead...?
        let date = $(this).val().replace(/\//g, '-').split('-'); //allow both slashes and dashes
        let input_id = 'input[name=' + $(this).attr('name').split('_').slice(0, -1).join('_') + ']';

        if (date.length !== 3) {
            // need exactly 3 elements, else it's not a valid date
            $(input_id).val(0);
            $(this).val(null);
            return;
        }

        // can be either yyyy-mm-dd or dd-mm-yyyy
        if (date[0].length === 4) {
            date = date.reverse();
            $(this).val(date[2] + '-' + date[1] + '-' + date[0]);
        } else {
            $(this).val(date[0] + '-' + date[1] + '-' + date[2]);
        }

        // store timestamp in hidden 'actual' input field
        let date_obj = new Date(parseInt(date[2]), parseInt(date[1]) - 1, parseInt(date[0]));
        let timestamp = Math.floor(date_obj.getTime() / 1000);
        timestamp -= date_obj.getTimezoneOffset() * 60;  //correct for timezone

        if (isNaN(timestamp)) {
            // invalid date
            $(this).val(null);
            $(input_id).val(0);
        } else {
            $(input_id).val(timestamp);
        }
    },

    annotation_label: {
        handle: function (e) {
            e.preventDefault();
            let target = e.target;
            if (target.tagName !== 'SPAN') {
                target = $(target).parents('span')[0];
            }

            const current_label = target.innerText;
            const callback_url = find_parent(target, 'div').getAttribute('data-label-edit-href');

            popup.dialog(
                '<p>Edit the label for this annotation:</p>' +
                '<label>Label: <input type="text" id="new-annotation-label" name="label" value="' + current_label + '"></label>',
                'Edit annotation label',
                function () {
                    const new_label = document.querySelector('#new-annotation-label').value.trim();
                    const payload = {'annotation_id': target.getAttribute('data-annotation-id'), 'label': new_label };
                    fetch(callback_url, {
                        method: 'POST',
                        body: JSON.stringify(payload),
                        headers: {
                            'Content-Type': 'application/json'
                        },
                    })
                        .then((response) => response.json())
                        .then(response_json => {
                            if(response_json.status && response_json.status === 'success') {
                                target.childNodes[1].nodeValue = ' ' + new_label;
                            }
                        })
                        .catch((error) => {
                            popup.alert('There was an error changing the annotation label. Refresh and try again later.');
                        });
                }
            );
        }
    },

    label: {
        init: function () {
            $(this).append('<button class="edit-dataset-label"><i class="fa fa-edit"></i><span class="sr-only">Edit label</span></button>');
        },

        handle: function (e) {
            let button = $(this).parents('div').find('button');
            if (e.type == 'keydown' && e.keyCode != 13) {
                return;
            }

            if (button.find('i').hasClass('fa-check')) {
                query.label.save(e, button);
            } else {
                query.label.edit(e, button);
            }
        },

        edit: function (e, self) {
            e.preventDefault();
            let current = $(self).parent().find('span a');
            let field = $('<input id="new-dataset-label">');
            field.val(current.text());
            field.attr('data-url', current.attr('href'));
            current.replaceWith(field);
            field.focus().select();
            $(self).parent().find('i.fa').removeClass('fa-edit').addClass('fa-check');
        },

        save: function (e, self) {
            e.preventDefault();
            let field = $(self).parent().find('input');
            let new_label = field.val();
            let dataset_key = $('article.result').attr('data-dataset-key');

            $.post({
                dataType: "json",
                url: '/api/edit-dataset-label/' + dataset_key + '/',
                data: {label: new_label},
                cache: false,

                success: function (json) {
                    let link = $('<a href="' + json.url + '">' + json.label + '</a>');
                    field.replaceWith(link);
                    $(self).parent().find('i.fa').removeClass('fa-check').addClass('fa-edit');
                },
                error: function (response) {
                    popup.alert('Oh no! ' + response.text, 'Error');
                }
            });
        }
    },

    convert_dataset: function (self) {
        let datasource = $(self.target).val();
        let dataset_key = $('article.result').attr('data-dataset-key');

        if (datasource.length > 0) {
            $.post({
                dataType: "json",
                url: '/api/convert-dataset/' + dataset_key + '/',
                data: {to_datasource: datasource},
                cache: false,

                success: function (json) {
                    location.reload();
                },
                error: function (response) {
                    popup.alert('Oh no! ' + response.text, 'Error');
                }
            });
        }
    },

    add_owner: function (e) {
        e.preventDefault();
        let target = e.target;
        if(target.tagName !== 'A') {
            target = $(target).parents('a')[0];
        }

        popup.dialog(
            '<p>Owners have full privileges; viewers can only view a dataset. You can add users as owners, or all ' +
            'users with a given tag by adding <samp>tag:example</samp> as username.</p>' +
            '<label>Username: <input type="text" id="new-dataset-owner" name="owner"></label>' +
            '<label>Role: ' +
            '  <select id="new-dataset-role" name="role"><option value="owner">Owner</option><option value="viewer">Viewer</option>' +
            '</select></label>',
            'Grant access to dataset',
            function () {
                let dataset_key = document.querySelector('article.result').getAttribute('data-dataset-key');
                let name = document.querySelector('#new-dataset-owner').value;
                let role = document.querySelector('#new-dataset-role').value;
                let body = new FormData();
                body.append('name', name);
                body.append('key', dataset_key);
                body.append('role', role);
                fetch(target.getAttribute('href').replace(/redirect/, ''), {
                    method: 'POST',
                    body: body
                })
                    .then((response) => response.json())
                    .then((data) => {
                        if(!data['html']) {
                            popup.alert('There was an error adding the owner to the dataset. ' + data['error']);
                        } else {
                            document.querySelector('.dataset-owner-list ul').insertAdjacentHTML('beforeend', data['html']);
                        }
                    })
                    .catch((error) => {
                        document.querySelector('.dataset-owner-list').classList.add('flash-once-error');
                        popup.alert('There was an error adding the owner to the dataset. Refresh and try again later.');
                    });
            }
        );
    },

    remove_owner: function (e) {
        e.preventDefault();
        let target = e.target;
        if(target.tagName !== 'A') {
            target = $(target).parents('a')[0];
        }

        popup.confirm('Are you sure you want to remove access from the dataset for this user or tag? This cannot be undone.', 'Confirm', function () {
            let owner = target.parentNode.getAttribute('data-owner');
            let dataset_key = document.querySelector('article.result').getAttribute('data-dataset-key');
            let body = new FormData();
            body.append('name', owner);
            body.append('key', dataset_key);
            fetch(target.getAttribute('href').replace(/redirect/, ''), {
                method: 'DELETE',
                body: body
            })
                .then((response) => response.json())
                .then(data => {
                    console.log(data);
                    if (data['error']) {
                        popup.alert('There was an error removing the owner from the dataset. ' + data['error']);
                    } else {
                        document.querySelector('[data-owner="' + owner + '"]').remove();
                    }
                })
                .catch((error) => {
                    console.log(error);
                    document.querySelector('.dataset-owner-list').classList.add('flash-once-error');
                    popup.alert('There was an error removing the owner from the dataset. Refresh and try again later.');
                });
        });
    }

};

export const module = query;