var dot_ticker = 0;
var timeout;
var query_key = null;
var poll_interval;

/**
 * Page init
 */
$(init);

function init() {
    setInterval(query.update_status, 4000);
    postprocessor.collapse_options();

    // Start querying when go button is clicked
    $('#query-form').bind('submit', function (e) {
        e.preventDefault();
        query.start();
        $('#whole-form').attr('disabled', 'disabled');
    });

    // Enable date selection when 'filter on time' checkbox is checked
    $('#check-time').on('change', function () {
        $('.input-time').attr('disabled', !this.checked);
    });

    // Change the option and label for keyword-dense threads according to body input
    $('#body-input').on('input', function () {
        input_string = $('#body-input').val();

        if (input_string === '') {
            $('.density-keyword').html('keyword');
            $('.input-dense').prop('disabled', true);
            $('#check-keyword-dense-threads').prop('checked', false)
        } else {
            $('.input-dense').prop('disabled', false);
            if (input_string.length > 7) {
                $('.density-keyword').html(input_string.substr(0, 4) + '...')
            } else {
                $('.density-keyword').html(input_string)
            }
        }
    });

    //platform select boxes trigger an update of the boards available for the chosen platform
    $('#platform-select').on('change', query.update_boards);
    $('#platform-select').trigger('change');

    //controls to change which results show up in overview
    $('.view-controls button').hide();
    $('.view-controls input, .view-controls select, .view-controls textarea').on('change', function () {
        $(this).parents('form').trigger('submit');
    });

    //tooltips
    $(document).on('mousemove', '.tooltip-trigger', tooltip.show);
    $(document).on('mouseout', '.tooltip-trigger', tooltip.hide);
    $(document).on('click', '.tooltip-trigger', tooltip.toggle);

    // subsubsubquery interface bits
    $(document).on('click', '.expand-postprocessors', postprocessor.toggle);
    $(document).on('click', '.control-postprocessor', postprocessor.queue);

    //allow opening given analysis path via anchor links
    navpath = window.location.hash.substr(1);
    if (navpath.substring(0, 4) === 'nav=') {
        let analyses = navpath.substring(4).split(',');
        let navigate = setInterval(function () {
            if (analyses.length === 0) {
                clearInterval(navigate);
                return;
            }
            let breadcrumb = analyses.shift();
            $('#subquery-' + breadcrumb + ' > .query-core > button').trigger('click');
        }, 25);
    }
}

/**
 * Post-processor handling
 */
postprocessor = {
    /**
     * Toggle options for a postprocessor
     *
     * A bit more involved than it should be, but this way it looks nicer because
     * of the animation...
     */
    toggle: function (e) {
        let mode = 'on';
        if ($(this).hasClass('active')) {
            mode = 'off';
            $(this).removeClass('active');
        } else {
            $(this).addClass('active');
        }

        e.preventDefault();

        let block = $(this).parent().parent();
        let parent_block = $(block.parents('.subquery')[0]);
        let siblings = block.siblings();

        if (mode === 'off') {
            //trigger closing of lower levels
            let open_children = block.find('.subquery.focus');
            if (open_children.length > 0) {
                $(open_children[0]).find('> .query-core > .expand-postprocessors').trigger('click');
            }

            block.find('.sub-controls .expand-postprocessors.active').each(function () {
                $(this).trigger('click');
            });

            //close this level and any underlying
            siblings.attr('aria-expanded', 'true');
            block.attr('aria-expanded', null);
            block.removeClass('card').removeClass('focus');
            $(this).text($(this).attr('data-original'));
            block.find('> .details-only').attr('aria-expanded', 'true');

            if (parent_block) {
                parent_block.addClass('card').find('> .query-core').removeClass('card');
                parent_block.find('> .sub-controls > .details-only').attr('aria-expanded', 'true');
            }
        } else {
            //open this level and collapse siblings
            siblings.attr('aria-expanded', 'false');
            block.attr('aria-expanded', 'true');
            block.addClass('card').addClass('focus');
            block.find('> .details-only').attr('aria-expanded', 'true');

            if (siblings.length === 0) {
                $(this).attr('data-original', $(this).text()).text('Close');
            } else {
                let vowel = (siblings.length === 1) ? 'i' : 'e';
                $(this).attr('data-original', $(this).text()).text('Show ' + siblings.length + ' other analys' + vowel + 's of the query above');
            }

            if (parent_block) {
                parent_block.removeClass('card').find('> .query-core').addClass('card');
                parent_block.find('> .sub-controls > .details-only').attr('aria-expanded', 'false');
            }
        }
    },

    /**
     * Queue a post-processor
     *
     * Submit parameters and update result tree with new item if added
     *
     * @param e  Event that triggered queueing
     */
    queue: function (e) {
        e.preventDefault();
        if ($(this).text() === 'Options') {
            $(this).text('Queue');
            let li = $(this).parent().parent().parent();
            li.removeClass('collapsed').addClass('expanded');
            li.find('fieldset').css('height', li.attr('data-options-height') + 'px');
        } else {
            let form = $(this).parents('form');
            $.ajax(form.attr('action') + '?async', {
                'method': form.attr('method'),
                'data': form.serialize(),
                'success': function (response) {
                    if (response.messages.length > 0) {
                        alert(response.messages.join("\n\n"));
                    }

                    if (response.html.length > 0) {
                        let new_element = $(response.html);
                        let parent_list = $('#' + response.container + ' > .subquery-list');
                        new_element.appendTo($(parent_list));
                    }
                },
                'error': function (response) {
                    alert('The analysis could not be queued: ' + response.responseText)
                }
            });
        }
    },

    collapse_options: function () {
        $('.postprocessor-list li').each(function () {
            if ($(this).hasClass('collapsed') || $(this).hasClass('expanded')) {
                return;
            }
            let fieldset = $(this).find('fieldset');
            if (fieldset.length === 0) {
                return;
            }
            $(this).attr('data-options-height', fieldset.height());
            fieldset.css('height', '0');
            $(this).addClass('collapsed');
            $(this).find('button.control-postprocessor').text('Options');
        })
    }
};

/**
 * Query queueing and updating
 */
query = {
    /**
     * Tool window: start a query, submit it to the backend
     */
    start: function () {

        // Show loader
        let loader = $('.loader');
        loader.show();

        //check form input
        if (!query.validate()) {
            loader.hide();
            return;
        }

        let formdata = $('#query-form').serialize();

        // AJAX the query to the server
        $.post({
            dataType: "text",
            url: "/queue-query/",
            data: formdata,
            success: function (response) {
                console.log(response);

                // If the query is rejected by the server.
                if (response.substr(0, 14) === 'Invalid query.') {
                    $('.loader').hide();
                    alert(response);
                    $('#query_status .status_message .message').html(response);
                    $('#whole-form').removeAttr('disabled');
                }

                // If the query is accepted by the server.
                else {
                    $('#query_status .status_message .message').html('Query submitted, waiting for results');
                    query_key = response;
                    query.check(query_key);

                    // poll results every 2000 ms after submitting
                    poll_interval = setInterval(function () {
                        query.check(query_key);
                    }, 4000);
                }
            },
            error: function (error) {
                $('#query_status .status_message .message').html(error);
                $('#whole-form').removeAttr('disabled');
                console.log(error);
                $('#results').html('<h3>' + $('#dataselection option:selected').text() + " error</h3>");
                $('.loader').hide()
            }
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
            url: '/check_query/' + query_key,
            success: function (json) {
                console.log(json);

                let status_box = $('#query_status .status_message .message');
                let current_status = status_box.html();

                //
                if (json.status !== current_status && json.status !== "") {
                    status_box.html(json.status);
                }

                if (json.done) {
                    clearInterval(poll_interval);
                    let keyword = $('#body-input').val();
                    if (keyword === '') {
                        keyword = $('#subject-input').val();
                    }

                    $('#submitform').append('<a href="/results/' + json.key + '"><p>' + json.query + ' (' + json.rows + ' posts)</p></a>');
                    $('.loader').hide();
                    $('#query_status .status_message .dots').html('');
                    $('#whole-form').removeAttr('disabled');
                    $('#post-preview').html(json.preview);
                    alert('Query for \'' + keyword + '\' complete!');
                } else {
                    let dots = '';
                    for (let i = 0; i < dot_ticker; i += 1) {
                        dots += '.';
                    }
                    $('#query_status .status_message .dots').html(dots);

                    dot_ticker += 1;
                    if (dot_ticker > 3) {
                        dot_ticker = 0;
                    }
                }
            },
            error: function () {
                console.log('Something went wrong when checking query status')
            }
        });
    },


    /**
     * Fancy live-updating subquery status
     *
     * Checks if running subqueries have finished, updates their status, and re-enabled further
     * analyses if all subqueries have finished
     */
    update_status: function () {
        let queued = $('.running.subquery');
        if (queued.length === 0) {
            return;
        }

        let keys = [];
        queued.each(function () {
            keys.push($(this).attr('id').split('-')[1])
        });

        $.get({
            url: "/check_postprocessors/",
            data: {subqueries: JSON.stringify(keys)},
            success: function (json) {
                json.forEach(subquery => {
                    let target = $('#subquery-' + subquery.key);
                    let update = $(subquery.html);
                    update.attr('aria-expanded', target.attr('aria-expanded'));

                    if (target.attr('data-status') === update.attr('data-status')) {
                        return;
                    }

                    target.replaceWith(update);
                    $('#subquery-' + subquery.key).addClass('flashing');

                    if (!$('body').hasClass('result-page')) {
                        return;
                    }

                    if ($('.running.subquery').length == 0) {
                        $('.result-warning').animate({height: 0}, 250, function () {
                            $(this).remove();
                        });
                        $('.queue-button-wrap').removeClass('hidden');
                    }
                });
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

        if ($('#check-time').is(':checked')) {
            let min_date = $('#input-min-time').val();
            let max_date = $('#input-max-time').val();
            let url_max_date;
            let url_min_date;

            // Convert the minimum date string to a unix timestamp
            if (min_date !== '') {
                url_min_date = stringToTimestamp(min_date);

                // If the string was incorrectly formatted (could be on Safari), a NaN was returned
                if (isNaN(url_min_date)) {
                    valid = false;
                    alert('Please provide a minimum date in the format dd-mm-yyyy (like 29-11-2017).');
                }
            }

            // Convert the maximum date string to a unix timestamp
            if (max_date !== '' && valid) {
                url_max_date = stringToTimestamp(max_date);
                // If the string was incorrectly formatted (could be on Safari), a NaN was returned
                if (isNaN(url_max_date)) {
                    valid = false;
                    alert('Please provide a maximum date in the format dd-mm-yyyy (like 29-11-2017).');
                }
            }

            // Input can be ill-formed, like '01-12-90', resulting in negative timestamps
            if (url_min_date < 0 || url_max_date < 0 && valid) {
                valid = false;
                alert('Invalid date(s). Check the bar on top with details on date ranges of 4CAT data.');
            }

            // Make sure the first date is later than or the same as the second
            if (url_min_date >= url_max_date && url_min_date !== 0 && url_max_date !== 0 && valid) {
                valid = false;
                alert('The first date is later than or the same as the second.\nPlease provide a correct date range.');
            }
        }

        return valid;
    },


    /**
     * Update board select list for chosen platform
     */
    update_boards: function () {
        let platform = $('#platform-select option:selected').text();
        $('#whole-form').attr('disabled', true);
        $.get({
            url: '/get-boards/' + platform + '/',
            success: function (json) {
                let select;
                if (!json) {
                    alert('No boards available for platform ' + platform);
                    select = $('<span id="board-select">(No boards available)</span>');
                } else {
                    select = $('<select id="board-select" name="board">');
                    json.forEach(function (board) {
                        $('<option value="' + board + '">' + board + '</option>').appendTo(select);
                    });
                }
                $('#board-select').replaceWith(select);
                $('#whole-form').removeAttr('disabled');
            },
            error: function (err) {
                alert('No boards available for platform ' + platform + ' (' + err + ')');
                let select = $('<span id="board-select">(No boards available)</span>');
                $('#board-select').replaceWith(select);
                $('#whole-form').removeAttr('disabled');
            }
        });
    }
};

/**
 * Tooltip management
 */
tooltip = {
    /**
     * Show tooltip
     *
     * @param e  Event that triggered tooltip display
     * @param parent  Element the toolip describes
     */
    show: function (e, parent = false) {
        if (e) {
            e.preventDefault();
        }
        if (!parent) {
            parent = this;
        }
        let tooltip_container = $('#' + $(parent).attr('aria-controls'));
        if ($(tooltip_container).is(':hidden')) {
            let position = $(parent).position();
            let parent_width = parseFloat($(parent).css('width').replace('px', ''));
            $(tooltip_container).show();
            let width = parseFloat($(tooltip_container).css('width').replace('px', ''));
            let height = parseFloat($(tooltip_container).css('height').replace('px', ''));
            $(tooltip_container).css('top', (position.top - height - 5) + 'px');
            $(tooltip_container).css('left', (position.left + (parent_width / 2) - (width / 2)) + 'px');
        }
    },

    /**
     * Hide tooltip
     *
     * @param e  Event that triggered the toggle
     * @param parent  Element the tooltip belongs to
     */
    hide: function (e, parent = false) {
        if (!parent) {
            parent = this;
        }
        let tooltip_container = $('#' + $(parent).attr('aria-controls'));
        $(tooltip_container).hide();
    },
    /**
     * Toggle tooltip between shown and hidden
     * @param e  Event that triggered the toggle
     */
    toggle: function (e) {
        e.preventDefault();

        let tooltip_container = $('#' + $(this).attr('aria-controls'));
        if ($(tooltip_container).is(':hidden')) {
            tooltip.show(e, this);
        } else {
            tooltip.hide(e, this);
        }
    }
};

/**
 * Page-in-page popups
 */
popup_panel = {
    panel: false,
    blur: false,
    wrap: false,
    url: '',

    show: function (url, fade = true) {
        popup_panel.url = url;
        if (!popup_panel.blur) {
            popup_panel.blur = $('<div id="popup-blur"></div>');
            popup_panel.blur.on('click', popup_panel.hide);
            $('body').append(popup_panel.blur);
        }

        if (!popup_panel.panel) {
            popup_panel.panel = $('<div id="popup-panel"><div class="popup-wrap"></div></div>');
            popup_panel.wrap = popup_panel.panel.find('.popup-wrap');
            $('body').append(popup_panel.panel);
        }

        if (fade) {
            popup_panel.panel.addClass('loading');
            popup_panel.wrap.html('');
            popup_panel.panel.removeClass('closed').addClass('open');
            popup_panel.blur.removeClass('closed').addClass('open');
        }

        $.get(url).done(function (html) {
            popup_panel.wrap.animate({opacity: 1}, 250);
            popup_panel.panel.removeClass('loading');
            popup_panel.wrap.html(html);
        }).fail(function (html, code) {
            alert('The page could not be loaded (HTTP error ' + code + ').');
            popup_panel.hide();
        });

        postprocessor.collapse_options();
    },

    refresh: function () {
        popup_panel.wrap.animate({opacity: 0}, 250, function () {
            popup_panel.show(popup_panel.url, false);
        });
    },

    hide: function () {
        popup_panel.panel.removeClass('open').addClass('closed');
        popup_panel.blur.removeClass('open').addClass('closed');
    }
};

/**
 * Convert input string to Unix timestamp
 *
 * @param str  Input string, yyyy-mm-dd ideally
 * @returns {*}  Unix timestamp
 */
function stringToTimestamp(str) {
    // Converts a text input to a unix timestamp.
    // Only used in Safari (other browsers use native HTML date picker)
    let date_regex = /^\d{4}-\d{2}-\d{2}$/;
    let timestamp;
    if (str.match(date_regex)) {
        timestamp = (new Date(str).getTime() / 1000)
    } else {
        str = str.replace(/\//g, '-');
        str = str.replace(/\s/g, '-');
        let date_objects = str.split('-');
        let year = date_objects[2];
        let month = date_objects[1];
        // Support for textual months
        let testdate = Date.parse(month + "1, 2012");
        if (!isNaN(testdate)) {
            month = new Date(testdate).getMonth() + 1;
        }
        let day = date_objects[0];
        timestamp = (new Date(year, (month - 1), day).getTime() / 1000);
    }
    return timestamp;
}