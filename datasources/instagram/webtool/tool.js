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

        $.post({
            'url': '/api/datasource-call/instagram/authenticate/',
            'data': {"username": username, "password": password},
            'success': function (data) {
                if (data['success']) {
                    if (data['data']['error']) {
                        let message = 'Authentication failed.';
                        alert(message + data['data']['error-message']);

                    } else if (!data['data']['authenticated']) {
                        $('#instagram-checkpoint-link').attr('href', data['data']['checkpoint-link'])
                        $('#instagram-checkpoint').removeClass('hidden');

                    } else {
                        // all good, let's start the actual query
                        query.start();
                    }
                } else {
                    // we should have received an error message, if this
                    // happened something failed quite badly
                    alert('Big error');
                }
            }
        });

        return false;
    })
});