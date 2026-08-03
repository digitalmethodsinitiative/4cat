/**
 * Two-option toggle button
 *
 * Switches a .toggle button (see css/components/buttons.css) between its left
 * and right option. The button's `aria-checked` attribute is both the state
 * the styling keys on and where the default comes from, so which option a
 * toggle starts on is set in the markup and nowhere else:
 *
 *   <button type="button" class="toggle" role="switch" aria-checked="false"
 *           x-data="toggleButton" @click="flip()" :aria-checked="checked">
 *       <span>Left option</span>
 *       <span>Right option</span>
 *   </button>
 *
 * Flipping it dispatches a bubbling `toggle-change` carrying the new state, so
 * whatever the toggle switches between can live elsewhere on the page and
 * listen for it rather than the toggle having to know about it.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('toggleButton', () => ({
        checked: false,

        init() {
            this.checked = this.$el.getAttribute('aria-checked') === 'true';
        },

        flip() {
            this.checked = !this.checked;
            this.$dispatch('toggle-change', {checked: this.checked});
        }
    }));
});
