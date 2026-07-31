/**
 * Alpine scope for inline dataset previews.
 *
 * A 'view' button (components/preview-toggle.html) and the preview it opens
 * (components/preview.html) are rendered as siblings, so the component that
 * hosts both declares `x-data="datasetPreview"` and the `dataset-preview-host`
 * class on their common ancestor: the .module-card or .dataset-metadata around
 * a dataset card, or the .processor-preview-box in the processor slideout's
 * lineage tree.
 *
 * Rather than sliding an empty panel open and filling it in afterwards, the
 * first click fetches the preview while the button spins, and the panel slides
 * open once there is something to show. The fetch is htmx's (or, for iframe
 * previews, the browser's), triggered by the `preview-open` event dispatched on
 * the host; `loaded` keeps it to once per preview, so re-opening is instant.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('datasetPreview', () => ({
        open: false,
        big: false,
        loaded: false,
        loading: false,

        toggle() {
            if (this.open) {
                this.open = false;
                this.big = false;
            } else if (this.loaded) {
                this.open = true;
            } else {
                this.loaded = true;
                this.loading = true;
                // not bubbling: nested previews (the lineage tree) would
                // otherwise all load when the innermost one is opened
                this.$root.dispatchEvent(new CustomEvent('preview-open'));
            }
        },

        // called once the preview content has arrived, successfully or not
        show() {
            this.loading = false;
            this.open = true;
        },

        fullscreen() {
            this.big = !this.big;
        }
    }));
});
