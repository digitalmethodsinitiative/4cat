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
     */
    makeMultichoice: function () {
        //more user-friendly select multiple
        $('.multichoice-wrapper').each(function () {

            let wrapper = $(this);
            let select = $(this).find('select');
            let name = select.attr('name');
            let input = $('<input type="hidden" name="' + name + '">');

            wrapper.append(input);

            select.find('option').each(function () {
                let selected = $(this).is(':selected');
                let checkbox_choice = $('<label><input type="checkbox" name="' + name + ':' + $(this).attr('value') + '"' + (selected ? ' checked="checked"' : '') + '> ' + $(this).text() + '</label>');
                checkbox_choice.find('input').on('change', function () {
                    let checked = wrapper.find('input:checked').map(function () {
                        return $(this).attr('name').split(':')[1];
                    }).get();
                    input.val(checked.join(','));
                });
                wrapper.append(checkbox_choice);
            });
            select.remove();
        });
    },

    /**
     * Make multiselect select boxes so
     */
    makeMultiSelect: function () {
        // Multi-select choice menu requires some code.
        $('.multi-select-wrapper').each(function () {
            let wrapper = $(this);

            // do nothing if already expanded
            if (wrapper.find(".multi-select-input").length > 0) {
                return;
            }

            // get the data we need from the original select and remove it
            let select = wrapper.find('select');
            let name = select.attr('name');
            let given_options = {};
            let num_options = 0;
            let given_default = [];
            select.find('option').each((i, option) => {
                num_options += 1;
                option = $(option);
                given_options[option.attr("value")] = option.text();
                if (option.is(":selected")) {
                    given_default.push(option.attr("value"));
                }
            });
            select.remove();

            let selected = $('<div class="multi-select-selected ms-selected-' + name + '" />');
            let input = $('<input class="multi-select-input" name="' + name + '" hidden />');
            let options = $('<div class="multi-select-options ms-options-' + name + '"></div>');

            for (let option in given_options) {
                let selected = given_default.indexOf(option) > -1;
                let checkbox_choice = $('<label><input type="checkbox" name="' + name + ":" + option + '"' + (selected ? ' checked="checked"' : '') + '> ' + given_options[option] + '</label>');

                checkbox_choice.find('input').on('change', () => {
                    let checked_names = [];

                    // Remove all present labels
                    let labels = '.multi-select-selected.ms-selected-' + name;
                    $(labels).empty();

                    // Add labels for all  selected checkmarks
                    wrapper.find('input:checked').each((i, checked) => {
                        let checked_name = $(checked).attr('name').split(':')[1];
                        $(labels).append('<span class="property-badge"><i class="fa fa-fw fa-times"></i> ' + checked_name + '</span>');
                        checked_names.push(checked_name);
                    });

                    input.val(checked_names.join(","));

                });
                options.append(checkbox_choice);
            }

            // prepend in reverse order to not get issues with tooltip button
            wrapper.prepend(input);
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
        let value = $(this).text().replace(/^\s+|\s+$/g, '');
        $(this).parent().parent().find('input[name$=":' + value + '"]').prop("checked", false).trigger('change');
        $(this).remove();
    }
};

export const module = multichoice;