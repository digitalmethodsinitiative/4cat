/**
 * Create-dataset form handling
 *
 * The data source options themselves are loaded into the form via htmx when a
 * data source is selected; `requires` relations between options are handled
 * by Alpine (see alpine.form.js). This script handles what neither can:
 * the two-phase submission of the form.
 *
 * Queries are validated before they are run for real. For file uploads, only
 * a small snippet of the file (or, for zip archives, a listing of its
 * contents) is submitted for validation, so that invalid parameters do not
 * incur a potentially huge upload. Only when the server says the parameters
 * are valid is the form re-submitted in full.
 */
(function () {
    const SNIPPET_SIZE = 128 * 1024;  // 128K ought to be enough for everybody

    function read_file(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsText(file);
        });
    }

    function get_form() {
        return document.getElementById('query-form');
    }

    function get_notice() {
        return document.getElementById('query-form-notice');
    }

    function show_notice(html) {
        const notice = get_notice();
        if (notice) {
            notice.innerHTML = html;
            notice.scrollIntoView({behavior: 'smooth', block: 'center'});
        }
    }

    function set_busy(busy, message = null) {
        const button = document.getElementById('query-form-submit');
        if (!button) {
            return;
        }
        button.disabled = busy;
        if (busy) {
            button.setAttribute('data-original-content', button.innerHTML);
            button.innerHTML = '<i class="fa fa-spin fa-spinner" aria-hidden="true"></i> ' + message;
        } else if (button.getAttribute('data-original-content')) {
            button.innerHTML = button.getAttribute('data-original-content');
        }
    }

    /**
     * Build form data for submission
     *
     * For the validation phase, file uploads are replaced with a snippet of
     * the file, or a listing of contained files for zip archives.
     */
    async function build_formdata(form, extra_data, for_real) {
        let formdata = new FormData(form);

        if (!for_real) {
            const snippeted = new FormData();
            for (const [field, value] of formdata.entries()) {
                if (!(value instanceof File)) {
                    snippeted.append(field, value);
                    continue;
                }

                if (['application/zip', 'application/x-zip-compressed'].includes(value.type) && window.zip) {
                    // don't bother with a snippet for zip files (it won't be
                    // useful), but do send a list of files in the zip
                    const reader = new zip.ZipReader(new zip.BlobReader(value));
                    const entries = await reader.getEntries();
                    snippeted.append(field + '-entries', JSON.stringify(
                        entries.map(e => ({filename: e.filename, filesize: e.compressedSize}))
                    ));
                    snippeted.append(field, null);
                } else {
                    const sample_size = Math.min(value.size, SNIPPET_SIZE);
                    const blob = value.slice(0, sample_size);  // do not load whole file into memory

                    // make sure we're submitting utf-8 - read and then re-encode to be sure
                    const blob_text = await read_file(blob);
                    snippeted.append(field, new File([new TextEncoder().encode(blob_text)], value.name));
                }
            }
            formdata = snippeted;
        }

        if (extra_data) {
            for (const field in extra_data) {
                formdata.set(field, extra_data[field]);
            }
        }

        return formdata;
    }

    /**
     * Submit the query form
     *
     * First submits for validation only (with snippeted file uploads); when
     * the server reports the parameters are valid, re-submits in full with
     * the 'frontend-confirm' flag to actually queue the dataset.
     */
    async function submit(extra_data = null, for_real = false) {
        const form = get_form();

        // an explicitly confirmed submission (via the notice checkbox after
        // the server asked for confirmation) skips the validation phase, as
        // a confirmed validation-phase submission would queue a dataset with
        // truncated file uploads
        if (!for_real && new FormData(form).get('frontend-confirm')) {
            for_real = true;
        }

        let formdata;
        try {
            formdata = await build_formdata(form, extra_data, for_real);
        } catch (e) {
            show_notice('<p class="notice" role="alert"><i class="fa fa-warning" aria-hidden="true"></i> ' +
                'Could not read the uploaded file. Try again with a different file.</p>');
            return;
        }

        // cache cacheable values
        const options = form.querySelector('fieldset[data-datasource]');
        const datasource = options ? options.getAttribute('data-datasource') : '';
        form.querySelectorAll('.cacheable input').forEach(input => {
            localStorage.setItem(datasource + '.' + input.getAttribute('name'), input.value);
        });

        set_busy(true, for_real ? 'Starting data collection' : 'Validating parameters');

        fetch(form.getAttribute('action'), {method: 'POST', body: formdata})
            .then(response => response.json())
            .then(response => {
                if (response.status === 'error' || response.status === 'confirm') {
                    show_notice(response.html || ('<p class="notice" role="alert">' + response.message + '</p>'));
                } else if (response.status === 'validated') {
                    // parameters OK: submit for real, in full
                    submit({'frontend-confirm': true, ...response.keep}, true);
                    return;
                } else if (response.status === 'extra-form') {
                    // new form elements to fill in before the dataset can be
                    // created
                    show_notice('');
                    const extra = document.createElement('div');
                    extra.className = 'datasource-extra-input flash-once';
                    extra.innerHTML = response.html;
                    get_notice().before(extra);
                } else if (response.status === 'success') {
                    // dataset was queued: go look at it
                    window.location.href = response.url;
                    return;
                }
                set_busy(false);
            })
            .catch(() => {
                show_notice('<p class="notice" role="alert"><i class="fa fa-warning" aria-hidden="true"></i> ' +
                    '4CAT could not process your dataset. Try again later.</p>');
                set_busy(false);
            });
    }

    /**
     * Data source-specific form tweaks that cannot be expressed as `requires`
     * relations between options.
     */
    function toggle_option(name, visible) {
        const field = document.querySelector('#query-form [name=option-' + name + ']');
        if (!field) {
            return;
        }
        field.disabled = !visible;
        field.closest('.form-element').style.display = visible ? '' : 'none';
    }

    function handle_density() {
        // datasources may offer 'dense thread' options; these are
        // sufficiently generalised that they can be handled here
        const scope_field = document.querySelector('#query-form #forminput-search_scope');
        if (!scope_field) {
            return;
        }
        const scope = scope_field.value;

        toggle_option('scope_density', scope === 'dense-threads');
        toggle_option('scope_length', scope === 'dense-threads');
        toggle_option('valid_ids', scope === 'match-ids');
    }

    function handle_board_options() {
        // some boards/subforums for datasources could have differing options;
        // board-specific fields can be added with `board_specific` in the
        // datasource's Python configuration
        const board_field = document.querySelector('#query-form #forminput-board');
        const board_specific = document.querySelectorAll('#query-form .form-element[data-board-specific]');
        if (!board_field || !board_specific.length) {
            return;
        }

        board_specific.forEach(element => {
            element.style.display = 'none';
            element.querySelectorAll('input').forEach(input => {
                input.value = null;
                input.checked = false;
                input.disabled = true;
            });
        });
        document.querySelectorAll('#query-form .form-element[data-board-specific*="' + board_field.value + '"]').forEach(element => {
            element.style.display = '';
            element.querySelectorAll('input').forEach(input => {
                input.disabled = false;
            });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        const form = get_form();
        if (!form) {
            return;
        }

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            submit();
        });

        form.addEventListener('change', (e) => {
            if (e.target.id === 'forminput-search_scope') {
                handle_density();
            } else if (e.target.id === 'forminput-board') {
                handle_board_options();
            } else if (e.target.id === 'forminput-data_upload') {
                // a new file may make previously requested extra input fields obsolete
                document.querySelectorAll('.datasource-extra-input').forEach(el => el.remove());
            }
        });

        // when the options for a data source have been loaded, fill in
        // cached values and apply data source-specific tweaks
        document.getElementById('datasource-form').addEventListener('htmx:after:settle', () => {
            const options = form.querySelector('fieldset[data-datasource]');
            const datasource = options ? options.getAttribute('data-datasource') : '';
            form.querySelectorAll('.cacheable input').forEach(input => {
                const cached = localStorage.getItem(datasource + '.' + input.getAttribute('name'));
                if (cached !== null && cached !== 'undefined') {
                    input.value = cached;
                }
            });

            handle_density();
            handle_board_options();
        });
    });
})();
