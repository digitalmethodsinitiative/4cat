import {popup} from "./popup.js";
import {find_parent, hsv2hsl} from "./util.js";

export const ui_helpers = {
    /**
     * Initialize UI enhancements via event listeners
     */
    init: function () {
        $(document).on('click', '.toggle-button', ui_helpers.toggleButton);

        //confirm links
        $(document).on('click', '.confirm-first', ui_helpers.confirm);

        //confirm links
        $(document).on('click', '.prompt-first', ui_helpers.confirm_with_prompt);

        //long texts with '...more' link
        $(document).on('click', 'div.expandable a', ui_helpers.expandExpandable);

        //autocomplete text boxes
        $(document).on('input', 'input.autocomplete', ui_helpers.autocomplete);

        //tabbed interfaces
        $(document).on('click', '.tabbed .tab-controls a', ui_helpers.tabs);

        //table controls
        $(document).on('input', '.copy-from', ui_helpers.table_control);

        //copy value to clipboard
        if(navigator.clipboard) {
            $(document).on('click', '.copy-to-clipboard', ui_helpers.clipboard_copy);
        } else {
            // clipboard access not available
            document.querySelector('#tooltip-clipboard').remove();
            document.querySelectorAll('.copy-to-clipboard').forEach(e => e.classList.remove('copy-to-clipboard'));
        }

        //iframe flexible sizing
        $('iframe').on('load', ui_helpers.fit_iframe);

        // Controls to change which results show up in overview
        $('.view-controls button').hide();
        $('.view-controls input, .view-controls select, .view-controls textarea').on('change', function () {
            $(this).parents('form').trigger('submit');
        });

        // 'more...' expanders
        $('.has-more').each(function () {
            let max_length = parseInt($(this).attr('data-max-length'));
            let full_value = $(this).text();
            if (full_value.length < max_length) {
                return;
            }
            $(this).replaceWith('<div class="expandable">' + full_value.substring(0, max_length) + '<span class="sr-only">' + full_value.substring(max_length) + '</span><a href="#">...more</a></div>');
        });

        // special case - cannot really genericise this
        $('body').on('change', '#forminput-data_upload', function () {
            $('.datasource-extra-input').remove();
        });

        // special case - colour picker for the interface
        $('body').on('input', '.hue-picker', function() {
            let h = parseInt($(this).val());
            let s = $(this).attr('data-saturation') ? parseInt($(this).attr('data-saturation')) : 87;
            let v = $(this).attr('data-value') ? parseInt($(this).attr('data-value')) : 81;
            let target = $(this).attr('data-update-background');

            if ($(this).attr('data-update-layout')) {
                document.querySelector(':root').style.setProperty('--accent', hsv2hsl(h, s, v));
                document.querySelector(':root').style.setProperty('--highlight', hsv2hsl(h, s, 100));
                document.querySelector(':root').style.setProperty('--accent-alternate', hsv2hsl((h + 180) % 360, s, 90));
            }
            $(target).css('background-color', hsv2hsl(h, s, v));
        });
        $('.hue-picker').trigger('input');

        // special case - 4CAT name picker
        $('body').on('input', '#request-4cat_name', function() {
            let label = $(this).val();
            $('h1 span a').text(label);
        });
        $('#request-4cat_name').trigger('input');

        // special case - settings panel filter
        $(document).on('input', '.settings .inline-search input', function(e) {
            let matching_tabs = [];
            let query = e.target.value.toLowerCase();
            document.querySelectorAll('.tab-content').forEach((tab) => {
                let tab_id = tab.getAttribute('id').replace(/^tab-/, 'tablabel-');
                if(document.querySelector('#' + tab_id).textContent.toLowerCase().indexOf(query) >= 0) {
                    matching_tabs.push(tab_id);
                    return;
                }

                tab.querySelectorAll('.form-element').forEach((element) => {
                    let label = element.querySelector('label').textContent;
                    let help = element.querySelector('[role=tooltip]');
                    if(
                        element.querySelector('[name]').getAttribute('name').indexOf(query) >= 0
                        || label.toLowerCase().indexOf(query) >= 0
                        || (help && help.textContent.toLowerCase().indexOf(query) >= 0)
                    ) {
                        matching_tabs.push(tab_id);
                    }
                });
            });
            document.querySelectorAll('.tab-controls .matching').forEach((e) => e.classList.remove('matching'));
            if(query) {
                matching_tabs.forEach((tab_id) => document.querySelector('#' + tab_id).classList.add('matching'));
            }
        });

        // special case - admin user tags sorting
        const $tagOrder = $('#tag-order');
        // Check tagOrder present and jQuery UI loaded
        if ($tagOrder.length && $.fn && $.fn.sortable) {
            $tagOrder.sortable({
                cursor: 'ns-resize',
                handle: '.handle',
                items: '.implicit, .explicit',
                axis: 'y',
                update: function(e, ui) {
                    let tag_order = Array.from(document.querySelectorAll('#tag-order li[data-tag]')).map(t => t.getAttribute('data-tag')).join(',');
                    let body = new FormData();
                    body.append('order', tag_order);
                    fetch(document.querySelector('#tag-order').getAttribute('data-url'), {
                        method: 'POST',
                        body: body
                    }).then(response => {
                        if(response.ok) {
                            ui.item.addClass('flash-once');
                        } else {
                            ui.item.addClass('flash-once-error');
                        }
                    });
                }
            });
        }

        // special case - restart 4cat front-end
        $('button[name=action][value=restart-frontend]').on('click', function(e) {
            e.preventDefault();
            const button = $('button[name=action][value=restart-frontend]');
            const url = button.attr('data-url');
            $('.button-container button').attr('disabled', 'disabled');
            button.find('i').removeClass('fa-power-off').addClass('fa-sync-alt').addClass('fa-spin');
            fetch(url, {method: 'POST'}).then(response => response.json()).then(response => {
                popup.alert(response.message, 'Front-end restart: ' + response.status);
            }).catch(e => {}).finally(() => {
                button.find('i').removeClass('fa-sync-alt').removeClass('fa-spin').addClass('fa-power-off');
                $('.button-container button').removeAttr('disabled');
            });
        });
    },

    /**
     * Ask for confirmation before doing whatever happens when the event goes through
     *
     * @param e  Event that triggers confirmation
     * @param message  Message to display in confirmation dialog
     * @returns {boolean}  Confirmed or not
     */
    confirm: function (e, message = null) {
        let trigger_type = $(this).prop("tagName");

        if (!message) {
            let action = 'do this';

            if ($(this).attr('data-confirm-action')) {
                action = $(this).attr('data-confirm-action');
            }

            message = 'Are you sure you want to ' + action + '? This cannot be undone.';
        }

        if (trigger_type === 'A') {
            // navigate to link, but only after confirmation
            e.preventDefault();
            let url = $(this).attr('href');

            popup.confirm(message, 'Please confirm', () => {
                window.location.href = url;
            });

        } else if (trigger_type === 'BUTTON' || trigger_type === 'INPUT') {
            // submit form, but only after confirmation
            let form = $(this).parents('form');
            if (!form) {
                return true;
            }

            e.preventDefault();
            popup.confirm(message, 'Please confirm', () => {
                // we trigger a click, because else the BUTTON name is not
                // sent with the form
                $(this).removeClass('confirm-first');
                $(this).click();
                $(this).addClass('confirm-first');
            });
        }
    },

    /**
     * Ask for confirmation before doing whatever happens when the event goes through
     *
     * Also ask for some input to send with the confirmation, if given
     *
     * @param e  Event that triggers confirmation
     * @returns {boolean}  Confirmed or not
     */
    confirm_with_prompt: function (e) {
        let action = 'do this';

        if ($(this).attr('data-confirm-action')) {
            action = $(this).attr('data-confirm-action');
        }

        let method = $(this).attr('data-confirm-method') ? $(this).attr('data-confirm-method') : 'GET';
        let result = confirm('Please confirm that you want to ' + action + '. This cannot be undone.');
        let html = '';
        let url = $(this).attr('href');

        e.preventDefault();
        if (!result) {
            return false;
        } else {
            if ($(this).attr('data-confirm-var')) {
                html = '<input type="hidden" name="' + $(this).attr('data-confirm-var') + '" value="' + result + '">';
            }
            $('<form style="display: none;"/>').attr('method', method).attr('action', url).html(html).appendTo('body').submit().remove();
            return false;
        }
    },

    /**
     * Handle '...more' expandables
     * @param e  Event that triggers expanding or un-expanding
     */
    expandExpandable: function (e) {
        e.preventDefault();

        if ($(this).text() === '...more') {
            $(this).text('...less');
            $(this).parent().find('.sr-only').removeClass('sr-only').addClass('expanded');
        } else {
            $(this).text('...more');
            $(this).parent().find('.expanded').addClass('sr-only').removeClass('expanded');
        }
    },

    /**
     * Handle generic toggle button
     *
     * Uses the 'aria-controls' value of the triggering element to know what to make visible or hide
     *
     * @param e  Event that triggers toggling
     * @param force_close  Assume the event is un-toggling something regardless of current state
     */
    toggleButton: function (e, force_close = false) {
        if ((!e.target.hasAttribute('type') || e.target.getAttribute('type') !== 'checkbox') && typeof e.preventDefault === "function") {
            e.preventDefault();
        }

        const button_target = $(e.target).is('.toggle-button, .processor-queue-button') ? $(e.target) : $(e.target).parents('.toggle-button, .processor-queue-button')[0];

        let target = '#' + $(button_target).attr('aria-controls');
        let is_open = $(target).attr('aria-expanded') !== 'false';

        if (is_open || force_close) {
            $(target).animate({'height': 0}, 250, function () {
                $(this).attr('aria-expanded', false).css('height', '');
            });

            // Also collapse underlying panels that are still open
            $(target).find('*[aria-expanded=true]').attr('aria-expanded', false);

            if ($(this).find('i.fa.fa-minus')) {
                $(this).find('i.fa.fa-minus').addClass('fa-plus').removeClass('fa-minus');
            }
        } else {
            $(target).css('visibility', 'hidden').css('position', 'absolute').css('display', 'block').attr('aria-expanded', true);
            let targetHeight = $(target).height();
            $(target).css('aria-expanded', false).css('position', '').css('display', '').css('visibility', '').css('height', 0);
            $(target).attr('aria-expanded', true).animate({"height": targetHeight}, 250, function () {
                $(this).css('height', '');
            });

            if ($(this).find('i.fa.fa-plus')) {
                $(this).find('i.fa.fa-plus').addClass('fa-minus').removeClass('fa-plus');
            }
        }
    },

    autocomplete: function(e) {
        let source = e.target.getAttribute('data-url');
        if(!source) { return; }

        let datalist = e.target.getAttribute('list');
        if(!datalist) { return; }

        datalist = document.querySelector('#' + datalist);
        if(!datalist) { return; }

        let value = e.target.value;
        fetch(source, {method: 'POST', body: value})
            .then(e => e.json())
            .then(response => {
                datalist.querySelectorAll('option').forEach(o => o.remove());
                response.forEach(o => {
                    let option = document.createElement('option');
                    option.innerText = o;
                    datalist.appendChild(option);
                });
            });
    },

    tabs: function(e) {
        e.preventDefault();
        let link = e.target;
        let target_id = link.getAttribute('aria-controls');
        let controls = find_parent(link, '.tab-controls');
        controls.querySelector('.highlighted').classList.remove('highlighted');
        link.parentNode.classList.add('highlighted');
        controls.parentNode.parentNode.querySelector('.tab-container *[aria-expanded=true]').setAttribute('aria-expanded', 'false');
        document.querySelector('#' + target_id).setAttribute('aria-expanded', 'true');
        let current_tab = controls.parentNode.querySelector('input[name="current-tab"]');
        if(!current_tab) {
            controls.parentNode.insertAdjacentHTML('afterbegin', '<input type="hidden" name="current-tab" value="">');
            current_tab = controls.parentNode.querySelector('input[name="current-tab"]');
        }
        current_tab.value = target_id.replace(/^tab-/, '');
    },

    table_control: function(e) {
        let control = e.target;
        let value = control.getAttribute('type') === 'checkbox' ? control.checked : control.value;
        let table = $(control).parents('table');
        let class_match = [...e.target.classList].filter((e) => e.indexOf('d-') === 0);
        table[0].querySelectorAll('.copy-to.' + class_match).forEach((element) => {
            if ($(element).parents('.d-ignore').length > 0) {
                return;
            }
            if (element.getAttribute('type') === 'checkbox') {
                element.checked = value;
            } else {
                element.value = value;
            }
        });
    },

    clipboard_copy: async function(e) {
        if(!navigator.clipboard) {
            // non-HTTPS context
            return;
        }
        const target = find_parent(e.target, '.copy-to-clipboard', true);
        let copyable = target.getAttribute('data-clipboard-value');
        if(!copyable) {
            copyable = target.innerText;
        }
        await navigator.clipboard.writeText(copyable);
        target.classList.add('flash-once');
        setTimeout(() => target.classList.remove('flash-once'), 250);
    },

    /**
     * Fit an iframe to its content's offsetHeight
     *
     * Use max-height on iframe element to add an upper limit!
     *
     * @param e
     */
    fit_iframe: function(e) {
        let iframe_height = e.target.contentWindow.document.documentElement.offsetHeight;
        e.target.style.height = iframe_height + 'px';
    }
};

export const module = ui_helpers;