/**
 * Alpine scopes for the Explorer.
 *
 * There is not much here on purpose. The server renders the items, the
 * annotation inputs and the field editor, and htmx fetches and replaces them;
 * what is left for Alpine is the state that never needs to survive a request -
 * which pane is showing, how a field is being edited before it is saved, and
 * whether an annotation has made it to the database yet.
 */

/**
 * Which annotation fields the reader has folded away in the items.
 *
 * Kept in the address rather than in a scope, so that it survives a refresh and
 * can be linked to; the server reads the same parameter and renders the items
 * folded to begin with.
 *
 * @returns {string[]}  Field IDs, in no particular order
 */
function hiddenAnnotationFields() {
    const hidden = new URL(window.location).searchParams.get('hidden');
    return hidden ? hidden.split(',').filter(Boolean) : [];
}

/**
 * Fold the items and the eye buttons to match the address.
 *
 * Run after anything the Explorer swaps in: the items that arrive when paging
 * or sorting were asked for before the reader folded anything away, and the
 * field editor is re-rendered by a request that does not carry the parameter at
 * all. Rather than teaching every one of those requests to pass it along, what
 * lands is brought into line with the address afterwards.
 *
 * The classes are set here rather than bound with `:class` on purpose - a class
 * Alpine adds while binding an element that arrived in an htmx swap is undone
 * as that swap settles, and never re-applied.
 */
function syncAnnotationVisibility() {
    const hidden = hiddenAnnotationFields();

    document.querySelectorAll('[data-annotation-field]').forEach(annotation => {
        annotation.classList.toggle('is-hidden', hidden.includes(annotation.dataset.annotationField));
    });

    document.querySelectorAll('[data-annotation-field-toggle]').forEach(button => {
        const folded = hidden.includes(button.dataset.annotationFieldToggle);
        button.setAttribute('aria-pressed', folded ? 'true' : 'false');
        button.querySelector('i')?.classList.toggle('fa-eye-slash', folded);
        button.querySelector('i')?.classList.toggle('fa-eye', !folded);
    });
}

document.addEventListener('htmx:after:settle', syncAnnotationVisibility);

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
     * Which pane is open is part of where you are, so it is kept in the address
     * as `view=explore`. That is the same thing the page was rendered from, so
     * a refresh or a shared link opens on what was being looked at.
     *
     * @param {string} initial  Pane to open on: 'explore' or anything else
     */
    Alpine.data('datasetPanes', (initial = 'analyze') => ({
        exploring: initial === 'explore',

        init() {
            // fetches the pane as soon as it is shown, once - the same
            // arrangement the inline dataset preview uses. A pane that is open
            // to begin with is filled by its own `load` trigger instead, so
            // that it does not depend on this event arriving before htmx is
            // listening for it
            this.$watch('exploring', showing => {
                if (showing) {
                    this.$dispatch('explore-open');
                }
                this.rememberPane(showing);
            });
        },

        // replaced rather than pushed: flipping between the two panes is not
        // somewhere you navigated to, and the back button should still lead
        // away from the dataset rather than through every flip
        rememberPane(exploring) {
            const url = new URL(window.location);
            if (exploring) {
                url.searchParams.set('view', 'explore');
            } else {
                url.searchParams.delete('view');
            }

            if (url.href !== window.location.href) {
                history.replaceState(history.state, '', url);
            }
        }
    }));

    /**
     * One annotation's saving state.
     *
     * Declared on the .item-annotation around an input that posts itself. htmx
     * 4 reports the response on the request's own event, so one handler covers
     * both outcomes; nothing here touches the input, which is never swapped.
     *
     * Since there is no save button, the chip is the only thing that says
     * whether what is on screen is also what is stored, so it may only say
     * 'saved' when it is. A value can fail to be stored on either side: the
     * input may hold something it cannot make a value of, or the server may
     * refuse what it is sent. Both end up in the same 'refused' state, so a
     * field type that validates in a way nothing here knows about is covered
     * without this having to learn about it.
     */
    Alpine.data('annotationValue', () => ({
        state: 'idle',

        /**
         * Send the value, unless the input cannot stand behind it.
         *
         * A control that cannot read what was typed - letters in a number
         * field - reports its value as the empty string, and posting that
         * would quietly wipe the annotation that was there. One that breaks
         * its own constraints would store something the field does not accept.
         * In both cases what is on screen is not what would be stored, so the
         * request is called off (htmx checks whether this event was cancelled
         * before it makes one) and the chip says the value is not saved.
         *
         * @param {Event} event  The htmx:before:request event, from the input
         */
        saving(event) {
            const input = event.target;
            if (typeof input?.checkValidity === 'function' && !input.checkValidity()) {
                event.preventDefault();
                this.state = 'refused';
                return;
            }

            this.state = 'saving';
        },

        settle(event) {
            const status = event.detail?.ctx?.response?.status;
            if (status && status < 400) {
                this.state = 'saved';
            } else {
                // 400 is the server declining to store this value, which is
                // something the person who typed it can put right; anything
                // else went wrong on the way rather than in the value
                this.state = (status === 400) ? 'refused' : 'error';
            }
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
     * A refused save re-renders these rows as they were submitted, saying what
     * was wrong with each; the marks that puts on the inputs at fault are the
     * server's answer about what was sent, so they are dropped as soon as the
     * row is edited and the answer no longer describes it.
     *
     * The label's mark is the server's own class rather than a binding, and is
     * taken off by hand: a class Alpine adds while binding an element that
     * arrived in an htmx swap is undone again as the swap settles, and since
     * the value behind it never changes, the binding never re-applies it. The
     * option inputs do not have that problem - Alpine makes them itself, well
     * after the swap - so theirs stays a binding.
     *
     * @param {object} field  `{id, type, options}` as the field is currently
     *                        saved, plus `{invalidOptions, optionsRequired}`
     *                        from a save that was refused
     */
    Alpine.data('annotationField', (field = {}) => ({
        id: field.id,
        type: field.type || 'text',
        options: [],
        isFirst: false,
        isLast: false,
        invalidOptions: field.invalidOptions || [],
        optionsRequired: !!field.optionsRequired,

        init() {
            this.options = (field.options || []).map(value => this.newOption(value));
            this.ensureBlank();

            // a field that becomes a choice field needs something to choose from
            this.$watch('type', () => this.hasOptions() && this.ensureBlank());

            this.updateBoundaries();
            this.boundaryObserver = new MutationObserver(() => this.updateBoundaries());
            this.boundaryObserver.observe(this.$root.parentNode, {childList: true});
        },

        destroy() {
            this.boundaryObserver?.disconnect();
        },

        // what the last save said about this row stops being true the moment it
        // is edited: the marks come off, and the editor's notice is told to go
        // away, since it is about fields that are no longer what it describes
        edited() {
            this.$root.querySelector('.annotation-field-label')?.classList.remove('invalid');
            this.invalidOptions = [];
            this.optionsRequired = false;
            this.$dispatch('annotation-field-edited');
        },

        // a field that was never saved has nothing to delete server-side, so
        // its row is the whole of it and dropping the row is the deletion
        removeField() {
            this.$root.remove();
        },

        // folding a field away in the items is a way of reading them, not a
        // change to the dataset, so it is written to the address and nowhere
        // else - replaced rather than pushed, since it is not somewhere the
        // back button should have to walk through
        toggleVisibility() {
            const hidden = new Set(hiddenAnnotationFields());
            hidden.has(this.id) ? hidden.delete(this.id) : hidden.add(this.id);

            const url = new URL(window.location);
            if (hidden.size) {
                url.searchParams.set('hidden', [...hidden].join(','));
            } else {
                url.searchParams.delete('hidden');
            }
            history.replaceState(history.state, '', url);

            syncAnnotationVisibility();
        },

        // a blank option is only at fault when the field has no other - it is
        // the empty box the option that is missing would be typed into
        optionInvalid(option) {
            const value = option.value.trim();
            return value ? this.invalidOptions.includes(value) : this.optionsRequired;
        },

        updateBoundaries() {
            this.isFirst = !this.$root.previousElementSibling;
            this.isLast = !this.$root.nextElementSibling;
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
            if (this.isFirst) return;
            const previous = this.$root.previousElementSibling;
            if (previous) {
                this.$root.parentNode.insertBefore(this.$root, previous);
            }
        },

        moveDown() {
            if (this.isLast) return;
            const next = this.$root.nextElementSibling;
            if (next) {
                this.$root.parentNode.insertBefore(next, this.$root);
            }
        },
    }));
});
