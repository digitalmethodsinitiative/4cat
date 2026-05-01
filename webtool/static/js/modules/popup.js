export const popup = {
    /**
     * Set up containers and event listeners for popup
     */
    is_initialised: false,
    current_callback: null,

    init: function () {
        $('<div id="blur"></div>').appendTo('body');
        $('<div id="popup" role="alertdialog" aria-labelledby="popup-title" aria-describedby="popup-text"><div class="content"></div><button id="popup-close"><i class="fa fa-times" aria-hidden="true"></i> <span class="sr-only">Close popup</span></button></div>').appendTo('body');

        //popups
        $(document).on('click', '.popup-trigger', popup.show);
        $('body').on('click', '#blur, #popup-close, .popup-close', popup.hide);
        $('body').on('click', '.popup-execute-callback', function () {
            if (popup.current_callback) {
                popup.current_callback();
            }
            popup.hide();
        });
        $(document).on('keyup', popup.handle_key);

        popup.is_initialised = true;
    },

    alert: function (message, title = 'Notice') {
        if (!popup.is_initialised) {
            popup.init();
        }

        $('#popup').removeClass('confirm').removeClass('render').removeClass('dialog').addClass('alert');

        let wrapper = $('<div><h2 id="popup-title">' + title + '</h2><p id="popup-text">' + message + '</p><div class="controls"><button class="popup-close"><i class="fa fa-check" aria-hidden="true"></i> OK</button></div></div>');
        popup.render(wrapper.html(), false, false);
    },

    confirm: function (message, title = 'Confirm', callback = false) {
        if (!popup.is_initialised) {
            popup.init();
        }

        if (callback) {
            popup.current_callback = callback;
        }

        $('#popup').removeClass('alert').removeClass('render').removeClass('dialog').addClass('confirm');
        let wrapper = $('<div><h2 id="popup-title">' + title + '</h2><p id="popup-text">' + message + '</p><div class="controls"><button class="popup-close"><i class="fa fa-times" aria-hidden="true"></i> Cancel</button><button class="popup-execute-callback"><i class="fa fa-check" aria-hidden="true"></i> OK</button></div></div>');
        popup.render(wrapper.html(), false, false);
    },

    dialog: function(body, title = 'Confirm', callback = false) {
        if (!popup.is_initialised) {
            popup.init();
        }

        if (callback) {
            popup.current_callback = callback;
        }

        $('#popup').removeClass('alert').removeClass('render').removeClass('confirm').addClass('dialog');
        let wrapper = $('<div><h2 id="popup-title">' + title + '</h2><div id="popup-dialog">' + body + '</div><div class="controls"><button class="popup-close"><i class="fa fa-times" aria-hidden="true"></i> Cancel</button><button class="popup-execute-callback"><i class="fa fa-check" aria-hidden="true"></i> OK</button></div></div>');
        popup.render(wrapper.html(), false, false);
    },

    /**
     * Show popup, using the content of a designated container
     *
     * @param e  Event
     * @param parent  Parent, i.e. the button controlling the popup
     */
    show: function (e, parent) {
        if (!popup.is_initialised) {
            popup.init();
        }

        if (!parent) {
            parent = this;
        }

        if (e) {
            e.preventDefault();
        }

        $('#popup').removeClass('confirm').removeClass('alert').addClass('render');

        //determine target - last aria-controls value starting with 'popup-'
        let targets = $(parent).attr('aria-controls').split(' ');
        let popup_container = '';
        targets.forEach(function (target) {
            if (target.split('-')[0] === 'popup') {
                popup_container = target;
            }
        });
        popup_container = '#' + popup_container;

        if ($(parent).attr('data-load-from')) {
            popup.render('<iframe src="' + $(parent).attr('data-load-from') + '"></iframe>', true);
        } else {
            popup.render($(popup_container).html());
        }
    },

    render: function (content, is_fullsize = false, with_close_button = true) {
        //copy popup contents into container
        $('#popup .content').html(content);
        if (is_fullsize) {
            $('#popup').addClass('fullsize');
        } else {
            $('#popup').removeClass('fullsize');
        }
        $('#blur').attr('aria-expanded', true);
        $('#popup').attr('aria-expanded', true);

        if (with_close_button) {
            $('#popup-close').show();
        } else {
            $('#popup-close').hide();
        }

        $('#popup embed').each(function () {
            svgPanZoom(this, {contain: true});
        });
    },

    /**
     * Hide popup
     *
     * @param e  Event
     */
    hide: function (e) {
        $('#popup .content').html('');
        $('#blur').attr('aria-expanded', false);
        $('#popup').attr('aria-expanded', false);
    },

    /**
     * Hide popup when escape is pressed
     *
     * @param e
     */
    handle_key: function (e) {
        if (e.keyCode === 27 && $('#popup').attr('aria-expanded')) {
            popup.hide(e);
        }
    }
};

export const module = popup;