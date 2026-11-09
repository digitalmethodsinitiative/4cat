function abspos(el) {
    const rect = el.getBoundingClientRect();
    return [rect.left + window.scrollX, rect.top + window.scrollY];
}

const TOOLTIP_GAP = 5;

/**
 * The tooltip currently on screen, as `{trigger, tooltip}`, and a watcher for
 * its trigger going away.
 *
 * A tooltip does not live inside the thing it describes - it is a paragraph in
 * `#tooltips`, which outlives any one page state - so nothing takes it down
 * with its trigger. Hiding it on `mouseleave` alone leaves it stranded whenever
 * the trigger stops being there to leave: htmx swapping the button away after
 * it is clicked, or a slideout opening over it. Whatever is showing is
 * therefore tracked, so it can be taken down by something other than the
 * pointer.
 */
let active_tooltip = null;
let trigger_watcher = null;

function hide_active_tooltip() {
    if (!active_tooltip) {
        return;
    }

    active_tooltip.tooltip.classList.add('sr-only');
    active_tooltip = null;
    trigger_watcher?.disconnect();
    trigger_watcher = null;
}

/**
 * Is this trigger still something the pointer could be on?
 *
 * @param {Element} trigger  The element the tooltip describes
 * @returns {boolean}  Whether it is still in the page and visible
 */
function trigger_is_gone(trigger) {
    if (!trigger.isConnected) {
        return true;
    }

    return trigger.checkVisibility ? !trigger.checkVisibility() : false;
}

document.addEventListener('alpine:init', () => {
    const tooltips = document.createElement('section');
    tooltips.id = 'tooltips';
    document.querySelector('body').appendChild(tooltips);

    // a click is the start of whatever the button does - navigating, opening a
    // slideout, asking htmx for something that replaces the button - and none
    // of those leave the tooltip describing anything
    document.addEventListener('click', hide_active_tooltip, true);

    Alpine.directive('tooltip', (el, { value, expression }) => {
        el.alpine_side = value;
        let spec = 3;
        const tooltip_content = expression;
        if(!tooltip_content) {
            return;
        }
        const bits = ['tooltip', ...tooltip_content.toLowerCase().replace(/[^a-z0-9- ]/g, '').replace(/[\s+]/g, '-').split('-')];
        let tooltip_id;
        while (!tooltip_id || bits.length >= spec) {
            tooltip_id = bits.slice(0, spec).join('-');
            if (!document.getElementById(tooltip_id)) {
                break;
            }
            spec += 1;
        }
        if (!document.getElementById(tooltip_id)) {
            const tooltip = document.createElement('p');
            tooltip.setAttribute('role', 'tooltip');
            tooltip.textContent = tooltip_content;
            tooltip.classList.add('sr-only');
            tooltip.id = tooltip_id;
            document.querySelector('#tooltips').appendChild(tooltip);
        }
        el.setAttribute('aria-describedby', tooltip_id);
        el.addEventListener('mouseenter', show_tooltip);
        el.addEventListener('focus', show_tooltip);
        el.addEventListener('mouseleave', hide_tooltip);
        el.addEventListener('focusout', hide_tooltip);
    });
});

function show_tooltip(e, parent = false) {
    if (e) {
        e.preventDefault();
    }

    if (!e.target.getAttribute('aria-describedby')) {
        return;
    }
    const trigger = e.target;
    const tooltip_container_id = trigger.getAttribute('aria-describedby');
    const tooltip_container = document.getElementById(tooltip_container_id);

    // whatever was showing is not what the pointer is on any more
    hide_active_tooltip();

    tooltip_container.classList.remove('sr-only');
    tooltip_container.classList.remove('force-width');

    active_tooltip = {trigger: trigger, tooltip: tooltip_container};
    // only while something is showing, so the page is not watched for nothing
    trigger_watcher = new MutationObserver(() => {
        if (active_tooltip && trigger_is_gone(active_tooltip.trigger)) {
            hide_active_tooltip();
        }
    });
    trigger_watcher.observe(document.body, {
        childList: true, subtree: true,
        attributes: true, attributeFilter: ['class', 'style', 'hidden']
    });


    const [trigger_x, trigger_y] = abspos(trigger);
    const trigger_d = trigger.getBoundingClientRect();
    const tooltip_d = tooltip_container.getBoundingClientRect();

    let top_position, hor_position;
    if (trigger.alpine_side === 'side') {
        top_position = trigger_y + (trigger_d.height / 2) - (tooltip_d.height / 2);
        hor_position = trigger_x + trigger_d.width + TOOLTIP_GAP;
        if (hor_position + trigger_d.width + TOOLTIP_GAP > document.documentElement.clientWidth) {
            hor_position = trigger_x - TOOLTIP_GAP - tooltip_d.width;
        }

    } else {
        top_position = (trigger_y - tooltip_d.height - TOOLTIP_GAP);

        // if out of viewport, position below element instead
        if (top_position < window.scrollY) {
            top_position = trigger_y + tooltip_d.height + TOOLTIP_GAP;
        }

        // do the same for horizontal placement
        hor_position = Math.max(window.scrollX, trigger_x + (trigger_d.width / 2) - (tooltip_d.width / 2));
        if (hor_position + tooltip_d.width - window.scrollX > document.documentElement.clientWidth) {
            const scrollbar_width = window.innerWidth - document.documentElement.clientWidth;
            //console.log(scrollbar_width);
            hor_position = document.documentElement.clientWidth + window.scrollX - tooltip_d.width - 5 - scrollbar_width;
        }
    }

    tooltip_container.style.top = top_position + 'px';
    tooltip_container.style.left = hor_position + 'px';
}

function hide_tooltip(e) {
    if (!e.target.getAttribute('aria-describedby')) {
        return;
    }

    hide_active_tooltip();
}