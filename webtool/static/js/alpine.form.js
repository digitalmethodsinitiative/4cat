/**
 * Alpine scope for user-input forms.
 *
 * Forms rendered through `components/form-option.html` declare
 * `x-data="userinputForm"` on the form element. Option elements with a
 * `requires` setting use `x-show="met(...)"` to show or hide themselves based
 * on the current values of other fields in the same form.
 *
 * The requirement-evaluation logic mirrors UserInput._requirement_met() in
 * Python (common/lib/user_input.py), so hidden options match the ones the
 * server ignores when parsing input.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('userinputForm', () => ({
        // bumped on every (relevant) mutation so `met()` re-evaluates; the DOM
        // remains the single source of truth for field values, which keeps
        // this compatible with enhanced widgets (multichoice etc.) and
        // htmx-injected fields
        version: 0,

        init() {
            const bump = () => this.version++;
            this.$el.addEventListener('input', bump);
            this.$el.addEventListener('change', bump);
            // htmx may swap new fields into the form (e.g. data source options
            // or 'extra-form' follow-up fields)
            this.$el.addEventListener('htmx:after:settle', bump);
        },

        /**
         * Evaluate the requirements of a form element against the form state
         *
         * @param {string|string[]} reqs  The option's `requires` setting: a
         *   single expression, a &&- or ||-joined string, or an array (AND).
         * @returns {boolean}  Whether the option should be visible
         */
        met(reqs) {
            this.version;  // reactive dependency

            let req_list, combine_and;
            if (Array.isArray(reqs)) {
                // array: AND semantics — every requirement must be satisfied
                req_list = reqs;
                combine_and = true;
            } else if (reqs.indexOf('||') >= 0) {
                // pipe-separated alternatives: any one is sufficient (OR)
                req_list = reqs.split('||').map(r => r.trim());
                combine_and = false;
            } else if (reqs.indexOf('&&') >= 0) {
                // ampersand-separated conditions: all must hold (AND)
                req_list = reqs.split('&&').map(r => r.trim());
                combine_and = true;
            } else {
                req_list = [reqs];
                combine_and = true;
            }

            const results = req_list.map(req => {
                const m = /([a-zA-Z0-9_-]+)([!=$~^]+)(.*)/.exec(req);
                const field = m ? m[1] : req.trim();
                const value = this._field_value(field);
                if (value === undefined) {
                    return false;  // field not found in form: requirement not met
                }
                return this._requirement_met(req, value);
            });

            return combine_and ? results.every(r => r) : results.some(r => r);
        },

        /**
         * Current value of a named form field
         *
         * @param {string} field  Field name (without 'option-' prefix)
         * @returns {boolean|string|string[]|undefined}  boolean for
         *   checkboxes, array for multi-selects, string otherwise; undefined
         *   if the field does not exist in the form
         */
        _field_value(field) {
            const form = this.$el.closest('form') || this.$el;
            const element = form.querySelector("[name='option-" + field + "']");
            if (!element) {
                return undefined;
            }

            if (element.getAttribute('type') === 'checkbox') {
                return element.checked;
            } else if (element.multiple) {
                return Array.from(element.selectedOptions).map(o => o.value);
            } else {
                return element.value;
            }
        },

        /**
         * Evaluate a single requirement expression against a resolved value
         *
         * Supported operators:
         *   == / =   exact equality
         *   !=       negated equality
         *   ^=       value starts with         !^=  does not start with
         *   $=       value ends with           !$=  does not end with
         *   ~=       value contains (or, for arrays, is a member)
         *            !~=  does not contain / is not a member
         *
         * @param {string} req  Requirement expression, e.g. "field==value"
         * @param {boolean|string|string[]} other_value  The referenced field's value
         * @returns {boolean}  True if the requirement is satisfied
         */
        _requirement_met(req, other_value) {
            const match = /([a-zA-Z0-9_-]+)([!=$~^]+)(.*)/.exec(req);
            let operator, value;
            if (!match) {
                // no operator found: bare field name, check it is present and non-empty
                operator = '!=';
                value = '';
            } else {
                [, , operator, value] = match;
            }

            const negated = operator.startsWith('!');
            if (negated) {
                operator = operator.substring(1);
            }

            if (typeof other_value === 'boolean') {
                // boolean values come from toggle / checkbox inputs
                if (operator === '==' || operator === '=') {
                    // true matches "true"/"checked"; false matches ""/"false"
                    if (((other_value && ['', 'false'].includes(value)) || (!other_value && ['checked', 'true'].includes(value))) !== negated) {
                        return false;
                    }
                } else {
                    // non-equality operator on a boolean: check truthy/falsy the same way
                    if (((other_value && !['true', 'checked'].includes(value)) || (!other_value && !['', 'false'].includes(value))) !== negated) {
                        return false;
                    }
                }
                return true;
            }

            if (Array.isArray(other_value)) {
                if (other_value.length === 1) {
                    // single-item array: unwrap and treat as scalar below
                    other_value = other_value[0];
                } else if (operator === '~=') {
                    // multi-item array + ~=: is value a member of this array?
                    return (other_value.indexOf(value) < 0) === negated;
                } else if (!negated) {
                    // other operators on multi-item arrays are not meaningful
                    return false;
                }
                // negated non-~= on multi-item array: fall through to scalar checks
            }

            // scalar (or unwrapped single-item array) comparisons
            const str_other = String(other_value);
            if (operator === '^=' && str_other.startsWith(value) === negated) { return false; }
            else if (operator === '$=' && str_other.endsWith(value) === negated) { return false; }
            else if (operator === '~=' && (str_other.indexOf(value) >= 0) === negated) { return false; }
            else if ((operator === '==' || operator === '=') && (value === str_other) === negated) { return false; }

            return true;
        }
    }));
});

/**
 * Date proxying for `date` and `daterange` inputs
 *
 * Visible date inputs are named `option-X_proxy`; their value is converted to
 * a unix timestamp stored in the hidden `option-X` input that is actually
 * parsed server-side. (The server can salvage unproxied dates, but this keeps
 * the submitted values canonical.)
 */
document.addEventListener('change', (e) => {
    const proxy = e.target;
    if (proxy.tagName !== 'INPUT' || proxy.getAttribute('type') !== 'date' || !proxy.name.endsWith('_proxy')) {
        return;
    }

    const form = proxy.closest('form');
    const target_name = proxy.name.split('_').slice(0, -1).join('_');
    const target = form ? form.querySelector("input[name='" + target_name + "']") : null;
    if (!target) {
        return;
    }

    // allow both slashes and dashes
    let date = proxy.value.replace(/\//g, '-').split('-');
    if (date.length !== 3) {
        // need exactly 3 elements, else it's not a valid date
        target.value = 0;
        proxy.value = null;
        return;
    }

    // can be either yyyy-mm-dd or dd-mm-yyyy
    if (date[0].length === 4) {
        date = date.reverse();
        proxy.value = date[2] + '-' + date[1] + '-' + date[0];
    } else {
        proxy.value = date[0] + '-' + date[1] + '-' + date[2];
    }

    // store timestamp in hidden 'actual' input field
    const date_obj = new Date(parseInt(date[2]), parseInt(date[1]) - 1, parseInt(date[0]));
    let timestamp = Math.floor(date_obj.getTime() / 1000);
    timestamp -= date_obj.getTimezoneOffset() * 60;  // correct for timezone

    if (isNaN(timestamp)) {
        // invalid date
        proxy.value = null;
        target.value = 0;
    } else {
        target.value = timestamp;
    }
});
