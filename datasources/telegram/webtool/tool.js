$(document).ready(function () {
    let storage = window.localStorage;

    // populate form with locally cached values
    let fields = ["api_id", "api_hash", "api_phone"];
    for (field in fields) {
        field = fields[field]
        let value = storage.getItem('telegram.' + field);
        if (typeof value != 'undefined' && value !== 'undefined') {
            $('#query-' + field).val(value);
        }
    }

    // todo: not break submitting if user changes to other data source
    $('#query-form').off('submit');

    // starting a telegram query is a little more involved than simply
    // submitting the parameters and waiting for the result; we need
    // to confirm our API credentials first
    $('#query-form.telegram').on('submit', function (e) {
        let api_phone = $('#query-api_phone').val();
        let api_id = $('#query-api_id').val();
        let api_hash = $('#query-api_hash').val();

        // locally cache input values
        storage.setItem('telegram.api_id', api_id);
        storage.setItem('telegram.api_hash', api_hash);
        storage.setItem('telegram.api_phone', api_phone);

        let session_bit = '';
        if ($('#telegram-session').length > 0) {
            session_bit = '&session=' + $('#telegram-session').val();
        }

        let code_bit = '';
        if ($('#query-security').val()) {
            code_bit = '&code=' + $('#query-security').val();
        }

        $.get({
            'url': '/api/datasource-call/telegram/authenticate/?api_id=' + api_id + '&api_hash=' + api_hash + '&api_phone=' + api_phone + session_bit + code_bit,
            'success': function (data) {
                if (data['success']) {
                    if (data['data']['session'] && !$('#telegram-session').length > 0) {
                        $('<input type="hidden" name="session" value="' + data['data']['session'] + '" id="telegram-session">').appendTo('#query-form');
                    }

                    if (data['data']['error']) {
                        let message = 'Authentication failed. ';
                        alert(message + data['data']['error-message']);

                    } else if (!data['data']['authenticated']) {
                        alert('A security code has been sent to phone number ' + api_phone + '. Enter it to continue.');
                        $('#telegram-security').removeClass('hidden');

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