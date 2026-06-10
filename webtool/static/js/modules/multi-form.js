import {find_parent, reset_form_elements} from "./util.js";

export const multiForm = {
    init: function () {
        const actions = document.createElement('div');
        actions.className = 'multi-form-actions';

        const add_button = document.createElement('button');
        add_button.className = 'add-button action-button';
        add_button.textContent = '+';
        add_button.addEventListener('click', multiForm.add_item);

        const delete_button = document.createElement('button');
        delete_button.className = 'delete-button action-button';
        delete_button.textContent = 'x';
        delete_button.addEventListener('click', multiForm.delete_item);

        actions.appendChild(add_button);
        actions.appendChild(delete_button);

        document.querySelectorAll('.form-multi-option-wrapper').forEach(function (el) {
            el.addEventListener('click', multiForm.handle_click);
            el.querySelectorAll('li').forEach(function (el) {
                const el_actions = actions.cloneNode(true);
                el.appendChild(el_actions);
            });
            multiForm.renumber(el);
        });

    },

    handle_click: function (e) {
        if(!(e.target.classList.contains('add-button') || e.target.classList.contains('delete-button'))) {
            return true;
        }
        e.preventDefault();
        const wrapper = find_parent(e.target, 'ol');
        if(e.target.classList.contains('delete-button')){
            multiForm.delete_item(e);
        } else {
            multiForm.add_item(e);
        }
        multiForm.renumber(wrapper);
    },

    add_item: function (e) {
        const ol = find_parent(e.target, 'ol.form-multi-option-wrapper');
        const last_li = find_parent(e.target, 'li');
        const clone = last_li.cloneNode(true);
        reset_form_elements(clone)
        ol.appendChild(clone);
    },

    delete_item: function (e) {
        if(!confirm("Are you sure?")){
            return false;
        }
        const li = find_parent(e.target, 'li');
        const ol = find_parent(e.target, 'ol.form-multi-option-wrapper');

        if(ol.querySelectorAll('li').length > 1) {
            li.parentNode.removeChild(li);
        } else {
            // last element; do not remove, but reset to default
            reset_form_elements(li);
        }
    },

    renumber: function(parent) {
        let index = 1;
        parent.querySelectorAll('li').forEach(function (el) {
            el.setAttribute('data-multi-option-index', index);
            el.querySelector('.delete-button').classList.remove('hidden');
            multiForm.renumber_items(el, index);
            index += 1;
        })
        parent.querySelector('li:last-child .delete-button').classList.add('hidden');
    },

    renumber_items: function(parent, index) {
        const attributes = ['for', 'id', 'name'];
        parent.childNodes.forEach(child => {
            if (!(child instanceof HTMLElement)) {
                return;
            }
            for(const attribute of attributes) {
                if(child.hasAttribute(attribute)) {
                    child.setAttribute(attribute, child.getAttribute(attribute).replace(/-[0-9]+-/, `-${index}-`));
                }
            }
            multiForm.renumber_items(child, index);
        });
    }

}

export const module = multiForm;