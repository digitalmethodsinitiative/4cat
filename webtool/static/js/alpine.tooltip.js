function abspos(el) {
    const rect = el.getBoundingClientRect();
    return [rect.left + window.scrollX, rect.top + window.scrollY];
}

const TOOLTIP_GAP = 5;

document.addEventListener('alpine:init', () => {
    const tooltips = document.createElement('section');
    tooltips.id = 'tooltips';
    document.querySelector('body').appendChild(tooltips);

    Alpine.directive('tooltip', el => {
        let spec = 3;
        const tooltip_content = el.getAttribute('x-tooltip');
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
    tooltip_container.classList.remove('sr-only');
    tooltip_container.classList.remove('force-width');


    const [trigger_x, trigger_y] = abspos(trigger);
    const trigger_d = trigger.getBoundingClientRect();
    const tooltip_d = tooltip_container.getBoundingClientRect();

    let top_position, hor_position;
    if (trigger.hasAttribute('x-tooltip-side')) {
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

    document.getElementById(e.target.getAttribute('aria-describedby')).classList.add('sr-only');
}