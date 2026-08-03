/**
 * Alpine scopes for the Explorer.
 *
 * There is not much here on purpose. The server renders the items, the
 * annotation inputs and the field editor, and htmx fetches and replaces them;
 * what is left for Alpine is the state that never needs to survive a request -
 * which pane is showing, how a field is being edited before it is saved, and
 * whether an annotation has made it to the database yet.
 */
document.addEventListener('alpine:init', () => {
    /**
     * The two panes below the dataset metadata.
     *
     * Declared on the element wrapping both. The 'Analyze / Annotate & Explore'
     * toggle sits in the dataset card, outside this element, and announces
     * itself with a `toggle-change` event; this scope only decides what that
     * means. The Explorer pane is empty until it is first shown, so switching
     * to it the first time asks htmx to fill it.
     *
     * @param {string} initial  Pane to open on: 'explore' or anything else
     */
    Alpine.data('datasetPanes', (initial = 'analyze') => ({
        exploring: false,

        init() {
            // fetches the pane as soon as it is shown, once - the same
            // arrangement the inline dataset preview uses
            this.$watch('exploring', showing => showing && this.$dispatch('explore-open'));

            if (initial === 'explore') {
                // after this element is bound, so the watcher above is in place
                // and htmx has processed the pane's trigger
                this.$nextTick(() => this.exploring = true);
            }
        }
    }));

    /**
     * One annotation's saving state.
     *
     * Declared on the .item-annotation around an input that posts itself. htmx
     * 4 reports the response on the request's own event, so one handler covers
     * both outcomes; nothing here touches the input, which is never swapped.
     */
    Alpine.data('annotationValue', () => ({
        state: 'idle',

        saving() {
            this.state = 'saving';
        },

        settle(event) {
            const status = event.detail?.ctx?.response?.status;
            this.state = (status && status < 400) ? 'saved' : 'error';
        }
    }));

    /**
     * One row of the annotation field editor.
     *
     * The row itself is the server's markup; this holds the parts of it that
     * only exist while it is being edited. Options are kept as objects rather
     * than plain strings so that each input keeps its identity as the list is
     * added to and removed from, and the field someone is typing in is not
     * re-created under them.
     *
     * @param {object} field  `{type, options}` as the field is currently saved
     */
    Alpine.data('annotationField', (field = {}) => ({
        type: field.type || 'text',
        options: [],

        init() {
            this.options = (field.options || []).map(value => this.newOption(value));
            this.ensureBlank();

            // a field that becomes a choice field needs something to choose from
            this.$watch('type', () => this.hasOptions() && this.ensureBlank());
        },

        newOption(value = '') {
            return {id: crypto.randomUUID(), value: value};
        },

        hasOptions() {
            return this.type === 'dropdown' || this.type === 'checkbox';
        },

        // there is always exactly one empty option at the end to type into, so
        // adding one is never a separate action
        ensureBlank() {
            if (!this.options.some(option => !option.value.trim())) {
                this.options.push(this.newOption());
            }
        },

        removeOption(option) {
            this.options = this.options.filter(other => other.id !== option.id);
            this.ensureBlank();
        },

        // the order fields are saved in is the order their rows are in, so
        // moving a row is all it takes to reorder them
        moveUp() {
            const previous = this.$root.previousElementSibling;
            if (previous) {
                this.$root.parentNode.insertBefore(this.$root, previous);
            }
        },

        moveDown() {
            const next = this.$root.nextElementSibling;
            if (next) {
                this.$root.parentNode.insertBefore(next, this.$root);
            }
        },

        // removing the row removes the field from the form, which is what tells
        // the server it was deleted - it asks for confirmation before acting on
        // that, so nothing is lost here
        removeField() {
            this.$root.remove();
        }
    }));
});
