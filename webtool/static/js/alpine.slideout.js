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
/**
 * Search state for a module grid (components/module-grid.html).
 *
 * The cards filter themselves against `moduleSearch`, so any page rendering a
 * grid needs this in scope: the module catalogue declares it directly
 * (`x-data="moduleGrid"`), the slideout folds it into its own scope below.
 */
const moduleGridScope = () => ({
    moduleSearch: '',

    // The one tag being filtered on, or null for no tag filter at all. Nothing
    // is selected to begin with, so the grid starts out showing everything and
    // the filter only ever narrows.
    selectedTag: null,

    tagSelected(tag) {
        return this.selectedTag === tag;
    },

    // Every tag shows its own colour until one is picked; from then on the
    // others dim, so the picked one reads as the single active filter. With
    // nothing picked there is nothing to contrast against, so none dim.
    tagDimmed(tag) {
        return Boolean(this.selectedTag) && this.selectedTag !== tag;
    },

    // picking a tag replaces whatever was picked before; picking the current
    // one again clears the filter, so the same click both sets and unsets
    toggleTag(tag) {
        this.selectedTag = this.selectedTag === tag ? null : tag;
    },

    clearTagFilter() {
        this.selectedTag = null;
    },

    /**
     * Whether a module card passes the search box and the tag filter
     *
     * With a tag picked, a module shows if that tag is among its own - so
     * picking `network` shows everything tagged `network`, whatever else it is
     * tagged as well.
     *
     * @param {HTMLElement} card  The .module-card to judge
     * @returns {boolean}  Whether it should be visible
     */
    moduleVisible(card) {
        const query = this.moduleSearch.toLowerCase().trim();
        if (query && !card.dataset.search.includes(query)) {
            return false;
        }

        if (!this.selectedTag) {
            return true;
        }

        // tags are joined on a pipe: they can contain spaces ('text analysis')
        // but never punctuation
        const tags = (card.dataset.tags || '').split('|').filter(Boolean);
        return tags.includes(this.selectedTag);
    },

    /**
     * Whether the current search and tag filter leave no module visible
     *
     * Cards hide themselves through their own `x-show`, so this only needs to
     * decide whether to show the 'nothing found' message.
     */
    noModuleResults() {
        const cards = [...document.querySelectorAll('#module-grid .module-card')];
        return Boolean(cards.length) && !cards.some(card => this.moduleVisible(card));
    }
});

document.addEventListener('alpine:init', () => {
    Alpine.data('moduleGrid', moduleGridScope);

    Alpine.data('moduleSlideout', () => ({
        ...moduleGridScope(),

        slideoutActive: false,
        slideoutTitle: '',
        // module the options level is showing; null keeps that level parked
        // off-screen and the grid's search box visible
        selectedModuleType: null,
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
            this.selectedTag = null;
            this.slideoutActive = true;
        },

        closeSlideout() {
            this.slideoutActive = false;
            this.selectedModuleType = null;
            this.moduleSearch = '';
            this.selectedTag = null;
        },

        closeOptions() {
            this.selectedModuleType = null;
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
