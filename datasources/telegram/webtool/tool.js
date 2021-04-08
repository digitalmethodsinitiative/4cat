$(document).ready(function () {
    let storage = window.localStorage;

    // todo: not break submitting if user changes to other data source
    $('#query-form').off('submit');
    $('#forminput-security-code').parent().addClass('hidden');

    // starting a telegram query is a little more involved than simply
    // submitting the parameters and waiting for the result; we need
    // to confirm our API credentials first
    $('#query-form.telegram').on('submit', function (e) {
        let api_phone = $('#forminput-api_phone').val();
        let api_id = $('#forminput-api_id').val();
        let api_hash = $('#forminput-api_hash').val();

        let code_bit = '';
        if ($('#forminput-security-code').val()) {
            code_bit = '&code=' + $('#forminput-security-code').val();
        }

        $.get({
            'url': '/api/datasource-call/telegram/authenticate/?api_id=' + api_id + '&api_hash=' + api_hash + '&api_phone=' + api_phone + code_bit,
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
                        $('#forminput-security-code').parent().removeClass('hidden');

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