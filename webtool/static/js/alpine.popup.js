/**
 * Alpine scope for a modal popup.
 *
 * The popup (components/popup.html) is a native <dialog>. The server renders
 * it and htmx swaps it into #popup-host; all that is left to do is the one
 * thing a <dialog> cannot do declaratively, which is open and close itself.
 *
 * showModal() is what puts the dialog in the top layer and makes it modal, and
 * with it come focus trapping, Esc to dismiss and an inert background. Since
 * Alpine initialises `x-data` in htmx-swapped markup by itself, the popup
 * needs no signal that it has landed - `init()` runs as it is inserted.
 *
 * The dialog is left in the DOM after it closes (a closed <dialog> is inert
 * and invisible), so its exit transition has something to run on; the next
 * popup swapped into the host replaces it.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('popup', () => ({
        init() {
            this.$root.showModal();
        },

        // $root, not $el: `dismiss()` is called from the buttons inside the
        // popup, and $el is whichever element the expression is being evaluated
        // on - the button - while $root is the <dialog> the scope belongs to
        dismiss() {
            this.$root.close();
        }
    }));
});
