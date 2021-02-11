$(document).ready(function () {
    let storage = window.localStorage;

    // populate form with locally cached values
    let fields = ["api_bearer_token"];
    for (field in fields) {
        field = fields[field]
        let value = storage.getItem('twitter.' + field);
        if (typeof value != 'undefined' && value !== 'undefined') {
            $('#twitter-' + field).val(value);
        }
    }

    // todo: not break submitting if user changes to other data source
    $('#query-form').off('submit');
    $('#query-form.twitterv2').on('submit', function (e) {
        e.preventDefault();
        let token = $('#twitter-api_bearer_token').val();

        // locally cache input values
        storage.setItem('twitter.api_bearer_token', token);

        query.start();
        return false;
    })
});