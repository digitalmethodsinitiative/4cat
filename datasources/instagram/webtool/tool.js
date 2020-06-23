$(document).ready(function () {
    let storage = window.localStorage;

    // populate form with locally cached values
    let fields = ["username", "password"];
    for (field in fields) {
        field = fields[field]
        let value = storage.getItem('instagram.' + field);
        if (typeof value != 'undefined' && value !== 'undefined') {
            $('#instagram-' + field).val(value);
        }
    }

    // todo: not break submitting if user changes to other data source
    $('#query-form').off('submit');

    $('#query-form.instagram').on('submit', function (e) {
        e.preventDefault();

        let username = $('#instagram-username').val();
        let password = $('#instagram-password').val();

        // locally cache input values
        storage.setItem('instagram.username', username);
        storage.setItem('instagram.password', password);

        query.start();
        return false;
    })
});