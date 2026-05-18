import {find_parent, getRelativeURL} from "./util.js";
import {popup} from "./popup.js";
import {ui_helpers} from "./ui-helpers.js";
import {query} from "./create-dataset.js";

/**
 * Post-processor handling
 */
const processor = {
    /**
     * Set up processor queueing event listeners
     */
    init: function () {
        // child of child of child etc interface bits
        $(document).on('click', '.processor-queue-button', processor.queue);

        // dataset deletion
        $(document).on('click', '.delete-link', processor.delete);
    },

    /**
     * Queue a post-processor
     *
     * Submit parameters and update result tree with new item if added
     *
     * @param e  Event that triggered queueing
     */
    queue: function (e, extra_data=null, run=false) {
        e.preventDefault();

        const form = find_parent(e.target, 'form');
        const run_button = form.querySelector('.processor-queue-button');

        if (run_button.innerText.includes('Run')) {
            // if it's a big dataset, ask if the user is *really* sure
            let parent = find_parent(run_button, 'li.child-wrapper');
            if (!parent) {
                parent = document.querySelector('.result-tree');
            }
            let num_rows = parseInt($('#dataset-' + parent.getAttribute('data-dataset-key') + '-result-count').attr('data-num-results'));

            if (num_rows > 500000) {
                if (!confirm('You are about to start a processor for a dataset with over 500,000 items. This may take a very long time and block others from running the same type of analysis on their datasets.\n\nYou may be able to get useful analysis results with a smaller dataset instead. Are you sure you want to start this analysis?')) {
                    return;
                }
            }

            run = true;
        }

        if(run) {
            let reset_form = true;
            let request_body = new FormData(form);
            if (extra_data) {
                for (let key in extra_data) {
                    request_body.set(key, extra_data[key]);
                }
            }

            fetch(form.getAttribute('data-async-action') + '?async', {method: form.getAttribute('method'), body: request_body})
                .then(function (response) {
                    if (!response.ok) {
                        throw response;
                    }
                    return response.json();
                })
                .then(function (response) {
                    if (response.hasOwnProperty('message') && response.message instanceof Array) {
                        response.message = response.message.join('\n\n');
                    }

                    if(['confirm', 'error', 'extra-form'].includes(response.status)) {
                        if (response['status'] === 'confirm') {
                            reset_form = false;
                            popup.confirm(response.message, 'Confirm', function () {
                                // re-send, but this time for real
                                processor.queue(e, {'frontend-confirm': true});
                            });
                            return;
                        } else if (response['status'] === 'error') {
                            reset_form = false;
                            if (response.hasOwnProperty("message") && response.message) {
                                popup.alert(response.message);
                            }
                            return;
                        } else if (response['status'] === 'extra-form') {
                            // new form elements to fill in
                            // some fancy css juggling to make it obvious that these need to be completed
                            reset_form = false;
                            const options_container = form.querySelector('.processor-options');

                            let extra_elements = $(response.html);
                            extra_elements.addClass('datasource-extra-input').css('visibility', 'hidden').css('position', 'absolute').css('display', 'block').appendTo(options_container);
                            let targetHeight = extra_elements.height();
                            extra_elements.css('position', '').css('display', '').css('visibility', '').css('height', 0);

                            extra_elements.animate({'height': targetHeight}, 250, function () {
                                $(this).css('height', '').addClass('flash-once');
                            });

                            return;
                        } else if (response.hasOwnProperty('message')) {
                            popup.alert(response.message);
                        }
                    }

                    if (response.html.length > 0) {
                        let new_element = $(response.html);
                        let container_id = response.container + ' .child-list';

                        let parent_list = $($(container_id)[0]);

                        // this is hardcoded, see next comment

                        let targetHeight = 68;
                        // the position of the newly inserted element is always 0 for some reason
                        // so we use the fact that it's inserted at the bottom of the source_dataset to
                        // infer it
                        let position = parent_list.offset().top + parent_list.height() - (targetHeight * 2);

                        let viewport_top = $(window).scrollTop();
                        let viewport_bottom = viewport_top + $(window).height();
                        new_element.appendTo($(parent_list));
                        new_element = $('body #' + new_element.attr('id'));
                        new_element.css('height', '0px').css('border-width', '0px').css('opacity', 0);

                        let expand = function () {
                            if ($('#child-tree-header').hasClass('collapsed')) {
                                $('#child-tree-header').attr('aria-hidden', 'false').removeClass('collapsed');
                            }
                            new_element.animate({'height': targetHeight, 'opacity': 1}, 500, false, function () {
                                $(this).css('height', '').css('opacity', '').css('border-width', '');
                            });
                        };

                        if (position < viewport_top || position > viewport_bottom) {
                            $('html,body').animate({scrollTop: position + 'px'}, 500, false, expand);
                        } else {
                            expand();
                        }
                    }
                })
                .catch(function (error) {
                    // Check if the error is a Response object
                    if (error instanceof Response) {
                        error.json().then((data) => {
                            // Handle the error response
                            popup.alert('The analysis could not be queued: ' + (data.error || data.message || 'Unknown error'), 'Warning');
                        }).catch(() => {
                            // Handle cases where the response is not JSON
                            popup.alert('The analysis could not be queued: ' + error.statusText, 'Warning');
                        });
                    } else {
                        // Handle other types of errors (e.g., network errors)
                        console.error(error);
                        popup.alert('A network error occurred. Please try again later.', 'Error');
                    }
                })
                .finally(() => {
                    if (reset_form && run_button.getAttribute('original-content')) {
                        run_button.innerHTML = run_button.getAttribute('original-content');
                        run_button.click();
                        run_button.innerHTML = run_button.getAttribute('original-content');
                        form.querySelectorAll('.delegated-option').forEach(n => n.remove());
                        form.reset();
                        ui_helpers.toggleButton({target: run_button});
                    }
                });
        } else {
            run_button.setAttribute('original-content', run_button.innerHTML);
            run_button.querySelector('.byline').innerText = 'Run';
            run_button.querySelector('.fa').classList.remove('.fa-cog');
            run_button.querySelector('.fa').classList.add('fa-play');
            ui_helpers.toggleButton({target: run_button});
        }
    },

    delete: async function (e) {
        e.preventDefault();
        let parent_with_key = $(this);

        popup.confirm('Are you sure? Deleted data cannot be restored.', 'Confirm', function () {
            while (!parent_with_key.attr('data-dataset-key') && parent_with_key.parent()) {
                parent_with_key = parent_with_key.parent();
            }

            const url = getRelativeURL('api/delete-dataset/' + parent_with_key.attr('data-dataset-key') + '/');
            fetch(url, {
                method: 'DELETE',
                body: {key: parent_with_key.attr('data-dataset-key')}
            }).then(function (response) {
                return response.json();
            }).then((json) => {
                $('li#child-' + json.key).animate({height: 0}, 200, function () {
                    $(this).remove();
                    if ($('.child-list.top-level li').length === 0) {
                        $('#child-tree-header').attr('aria-hidden', 'true').addClass('collapsed');
                    }
                });
                query.reset_form();
            }).catch((e) => {
                popup.alert('Could not delete dataset: ' + e, 'Error');
            });
        });
    }
};

export const module = processor;