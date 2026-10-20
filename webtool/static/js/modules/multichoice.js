export const multichoice = {
    /**
     * Set up multichoice events via event listeners
     */
    init: function () {
        // Multichoice inputs need to be loaded dynamically
        $(document).on('click', '.toggle-button, .processor-queue-button', function () {
            if ($(".multichoice-wrapper, .multi-select-wrapper").length > 0) {
                multichoice.makeMultichoice();
                multichoice.makeMultiSelect();
            }
        });

        // Filter multichoice on search
        $(document).on('input', '.multi-select-search > input', multichoice.filterMultiChoice);
        $(document).on('click', '.multi-select-selected > span', multichoice.removeMultiChoiceOption);
    },

    /**
     * Make multichoice select boxes so
     *
     * The options are shown as checkboxes, but the original select stays in
     * the form, hidden, and remains the field that is submitted: ticking a
     * checkbox selects the matching option. So the form sends the same values
     * whether or not this script runs: one per selected option.
     */
    makeMultichoice: function () {
        //more user-friendly select multiple
        $('.multichoice-wrapper').each(function () {
            let wrapper = $(this);
            let select = wrapper.find('select');

            // do nothing if already expanded
            if (select.hasClass('multichoice-select')) {
                return;
            }

            select.find('option').each(function () {
                wrapper.append(multichoice.makeCheckbox(select, this));
            });
            select.addClass('multichoice-select').hide();
        });
    },

    /**
     * Make multiselect select boxes so
     *
     * As with makeMultichoice, the original select stays in the form, hidden,
     * and is the field that is submitted. Option labels may contain HTML here,
     * so this is only for lists of options written in 4CAT's own code, not
     * for options taken from data such as column names.
     */
    makeMultiSelect: function () {
        // Multi-select choice menu requires some code.
        $('.multi-select-wrapper').each(function () {
            let wrapper = $(this);
            let select = wrapper.find('select');

            // do nothing if already expanded
            if (select.hasClass('multichoice-select')) {
                return;
            }

            let name = select.attr('name');
            let selected = $('<div class="multi-select-selected ms-selected-' + name + '" />');
            let options = $('<div class="multi-select-options ms-options-' + name + '"></div>');
            let num_options = 0;

            select.find('option').each((i, option) => {
                num_options += 1;
                let checkbox_choice = multichoice.makeCheckbox(select, option, true);

                checkbox_choice.find('input').on('change', () => {
                    // Show a label for each selected option
                    selected.empty();
                    for (let selected_option of select[0].selectedOptions) {
                        let label = $('<span class="property-badge"><i class="fa fa-fw fa-times"></i></span>');
                        label.attr('data-value', selected_option.value).append(document.createTextNode(' ' + selected_option.value));
                        selected.append(label);
                    }
                });
                options.append(checkbox_choice);
            });
            select.addClass('multichoice-select').hide();

            // prepend in reverse order to not get issues with tooltip button
            wrapper.prepend(selected);
            wrapper.prepend(options);

            if (num_options > 3) {
                let search = $('<div class="multi-select-search ms-search-' + name + '"><input name="filter-' + name + '" placeholder="Type to filter"></div>');
                options.append("<div class='no-match'>No matches</div>");
                $(options).find(".no-match").hide();
                wrapper.prepend(search);
            }
        });
    },

    /**
     * Make a checkbox that selects or deselects one option of a select
     *
     * The checkbox has no name, so it is not submitted itself; the select is.
     *
     * The option's label is shown as plain text, unless allow_html is set.
     * Only allow that for options whose labels are written in 4CAT's own code
     * (such as flag icons next to country names): labels taken from data,
     * such as a dataset's column names, could otherwise run code in the page.
     *
     * @param select  The select (jQuery object) the option belongs to
     * @param option  The option element
     * @param allow_html  Whether the label may contain HTML
     * @returns  A label (jQuery object) containing the checkbox
     */
    makeCheckbox: function (select, option, allow_html=false) {
        let checkbox = $('<input type="checkbox">').attr('data-value', option.value);

        // resetting the form returns both the select and the checkbox to their
        // initial state, so these need to match
        checkbox.prop('defaultChecked', option.defaultSelected).prop('checked', option.selected);

        checkbox.on('change', function () {
            option.selected = this.checked;
            // pass the change on as if the select itself was used, so that
            // e.g. fields that depend on its value are updated
            select[0].dispatchEvent(new Event('input', {bubbles: true}));
            select[0].dispatchEvent(new Event('change', {bubbles: true}));
        });

        let text = ' ' + $(option).text();
        return $('<label></label>').append(checkbox, allow_html ? $.parseHTML(text) : document.createTextNode(text));
    },

    filterMultiChoice: function (e) {
        let wrapper = $(e.target).parent().parent();
        let query = $(e.target).val().toLowerCase();
        let options = wrapper.find('.multi-select-options');
        let no_match = options.find(".no-match");

        no_match.hide();

        let match = false;
        options.find('label').each(function (i, label) {
            if (!$(label).text().toLowerCase().includes(query)) {
                // Doing this in an obtuse way to prevent resizing
                $(label).hide();
            } else {
                match = true;
                $(label).show();
            }
        });

        if (!match) {
            no_match.show();
        }
    },

    removeMultiChoiceOption: function () {
        let value = $(this).attr('data-value');
        $(this).parent().parent().find('input[type=checkbox]').filter((i, checkbox) => $(checkbox).attr('data-value') === value).prop("checked", false).trigger('change');
        $(this).remove();
    }
};

export const module = multichoice;