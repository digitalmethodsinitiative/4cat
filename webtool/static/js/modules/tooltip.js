const tooltip = {
    /**
     * Set up tooltip event listeners
     */
    init: function () {
        //tooltips
        $(document).on('mousemove', '.tooltip-trigger', tooltip.show);
        $(document).on('mouseout', '.tooltip-trigger', tooltip.hide);
        $(document).on('click', '.tooltip-trigger', tooltip.toggle);
    },

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

        // safe-get aria-controls
        const ariaControls = $(parent).attr('aria-controls') || '';
        if (!ariaControls) { return; }

        //determine target - last aria-controls value starting with 'tooltip-'
        let targets = ariaControls.split(' ');
        let tooltip_container_id = '';
        targets.forEach(function (target) {
            if (target.split('-')[0] === 'tooltip') {
                tooltip_container_id = target;
            }
        });

        let tooltip_container = $(document.getElementById(tooltip_container_id));
        let is_standalone = tooltip_container.hasClass('multiple');

        if (tooltip_container.is(':hidden')) {
            tooltip_container.removeClass('force-width');
            let position = is_standalone ? $(parent).offset() : $(parent).position();
            let parent_width = parseFloat($(parent).css('width').replace('px', ''));
            tooltip_container.show();

            // figure out if this is a multiline tooltip
            const content = tooltip_container.html();
            tooltip_container.html('1');
            const em_height = tooltip_container.height();
            tooltip_container.html(content);
            if (tooltip_container.height() > em_height) {
                tooltip_container.addClass('force-width');
            }

            let width = parseFloat(tooltip_container.css('width').replace('px', ''));
            let height = parseFloat(tooltip_container.css('height').replace('px', ''));
            let top_position = (position.top - height - 5);

            // if out of viewport, position below element instead
            if(top_position < window.scrollY) {
                top_position = position.top + parseFloat($(parent).css('height').replace('px', '')) + 5;
            }
            tooltip_container.css('top', top_position + 'px');

            // do the same for horizontal placement
            let hor_position = Math.max(window.scrollX, position.left + (parent_width / 2) - (width / 2));
            if(hor_position + tooltip_container.width() - window.scrollX > document.documentElement.clientWidth) {
                const scrollbar_width = window.innerWidth - document.documentElement.clientWidth;
                //console.log(scrollbar_width);
                hor_position = document.documentElement.clientWidth + window.scrollX - tooltip_container.width() - 5 - scrollbar_width;
            }
            tooltip_container.css('left', hor_position + 'px');
        }
    },

    /**
     * Hide tooltip
     *
     * @param e  Event that triggered the toggle
     * @param parent  Element the tooltip belongs to
     */
    hide: function (e, parent = false) {
        //determine target - last aria-controls value starting with 'tooltip-'
        if (!parent) {
            parent = this;
        }

        // safe-get aria-controls
        const ariaControls = $(parent).attr('aria-controls') || '';
        if (!ariaControls) { return; }

        let tooltip_container_id = '';
        ariaControls.split(' ').forEach(function (target) {
            if (target.split('-')[0] === 'tooltip') {
                tooltip_container_id = target;
            }
        });

        let tooltip_container = $(document.getElementById(tooltip_container_id));
        tooltip_container.hide();
    },
    /**
     * Toggle tooltip between shown and hidden
     * @param e  Event that triggered the toggle
     */
    toggle: function (e) {
        const ariaControls = $(this).attr('aria-controls') || '';
        if (!ariaControls) { return; }

        // pick last tooltip- id if multiple
        let tooltip_id = '';
        ariaControls.split(' ').forEach(function (t) {
            if (t.split('-')[0] === 'tooltip') { tooltip_id = t; }
        });

        let tooltip_container = $(document.getElementById(tooltip_id));
        if (tooltip_container.is(':hidden')) {
            tooltip.show(e, this);
        } else {
            tooltip.hide(e, this);
        }
    }
};

export const module = tooltip;