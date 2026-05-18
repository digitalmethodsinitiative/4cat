/**
 * Result page dataset trees navigation handlers
 */
const result_page = {
    /**
     * Set up navigation of result page dataset trees
     */
    init: function () {
        // dataset 'collapse'/'expand' buttons in result view
        $(document).on('click', '#expand-datasets', result_page.toggleDatasets);

        //allow opening given analysis path via anchor links
        let navpath = window.location.hash.substr(1);
        if (navpath.substring(0, 4) === 'nav=') {
            let analyses = navpath.substring(4).split(',');
            let navigate = setInterval(function () {
                if (analyses.length === 0) {
                    clearInterval(navigate);
                    return;
                }
                let breadcrumb = analyses.shift();
                if (analyses.length === 0) {
                    $('.anchor-child').removeClass('anchor-child');
                    $('#child-' + breadcrumb).addClass('anchor-child');
                }
                $('#child-' + breadcrumb + ' > .processor-expand > button').trigger('click');
            }, 25);
        }

        $('<label class="inline-search"><i class="fa fa-search" aria-hidden="true"></i><span class="sr-only">Filter:</span> <input type="text" placeholder="Filter"></label>').appendTo('.available-processors .section-subheader:first-child');
        $(document).on('keyup', '.result-page .inline-search input', result_page.filterProcessors);
    },

    filterProcessors: function (e) {
        let filter = $(this).val().toLowerCase();
        $('.available-processors .processor-list > li').each(function (processor) {
            let name = $(this).find('h4').text().toLowerCase();
            let description = $(this).find('header p').text().toLowerCase();
            if (name.indexOf(filter) < 0 && description.indexOf(filter) < 0) {
                $(this).hide();
            } else {
                $(this).show();
            }
        });
        // hide headers with no items
        $('.available-processors .category-subheader').each(function (header) {
            let processors = $(this).next().find('li:not(:hidden)');
            if(!processors.length) {
                $(this).hide();
            } else {
                $(this).show();
            }
        });
    },


    /**
     * Toggle the visibility of all datasets in a result tree
     *
     * @param e  Triggering event
     */
    toggleDatasets: function (e) {
        let new_text;
        let expanded_state;

        if ($(this).text().toLowerCase().indexOf('expand') >= 0) {
            new_text = 'Collapse all';
            expanded_state = true;
        } else {
            new_text = 'Expand all';
            expanded_state = false;
        }

        $(this).text(new_text);
        $('.processor-expand > button').each(function () {
            let controls = $('#' + $(this).attr('aria-controls'));
            if (controls.attr('aria-expanded')) {
                controls.attr('aria-expanded', expanded_state);
            }
        });
    }
};

export const module = result_page;