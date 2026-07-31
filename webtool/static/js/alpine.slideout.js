/**
 * Alpine scope for the module slideout.
 *
 * The slideout (components/module-slideout.html) is a two-level panel: a grid
 * of modules to pick from, and, sliding over it, the options form for the
 * module that was picked. It is used both for the processors that can run on a
 * dataset and for the data sources a new dataset can be created from, so
 * nothing in here is specific to either - the page that opens the slideout
 * decides what goes in the grid, by pointing the opening button's `hx-get` at
 * the relevant grid endpoint.
 *
 * Declared on the element wrapping both the opening button(s) and the slideout
 * itself (`x-data="moduleSlideout"`, typically the .dataset-container).
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('moduleSlideout', () => ({
        slideoutActive: false,
        slideoutTitle: '',
        // module the options level is showing; null keeps that level parked
        // off-screen and the grid's search box visible
        selectedModuleType: null,
        moduleSearch: '',
        // id of an element to scroll to once htmx has settled the swap that
        // creates it (e.g. a newly queued analysis)
        pendingScrollId: null,

        init() {
            // while the slideout covers the page, the page behind it should
            // not scroll along
            this.$watch('slideoutActive', active => document.body.classList.toggle('slideout-open', active));
        },

        /**
         * Open the slideout at the grid level
         *
         * The grid content itself is loaded by the htmx request on the button
         * that calls this. Note the verbose names: buttons opening the
         * slideout can sit in a nested scope of their own (a dataset card's
         * `datasetPreview`, which has its own `open`), and the innermost
         * scope wins.
         *
         * @param {string} title  Heading for the slideout
         */
        openSlideout(title = '') {
            this.slideoutTitle = title;
            this.selectedModuleType = null;
            this.moduleSearch = '';
            this.slideoutActive = true;
        },

        closeSlideout() {
            this.slideoutActive = false;
            this.selectedModuleType = null;
            this.moduleSearch = '';
        },

        closeOptions() {
            this.selectedModuleType = null;
        },

        /**
         * Whether the current search matches no module in the grid
         *
         * Cards hide themselves through their own `x-show`, so this only needs
         * to decide whether to show the 'nothing found' message.
         */
        noModuleResults() {
            const query = this.moduleSearch.toLowerCase().trim();
            return Boolean(query) && ![...document.querySelectorAll('#module-grid .module-card')]
                .some(card => card.dataset.search.includes(query));
        },

        scrollToAfterSettle(id) {
            this.pendingScrollId = id;
        },

        // bound to htmx's settle event; scrolls to whatever
        // `scrollToAfterSettle()` was last given, if it exists by now
        settle() {
            if (!this.pendingScrollId) {
                return;
            }

            const element = document.getElementById(this.pendingScrollId);
            if (element) {
                element.scrollIntoView({behavior: 'smooth', block: 'center'});
            }
            this.pendingScrollId = null;
        }
    }));
});
