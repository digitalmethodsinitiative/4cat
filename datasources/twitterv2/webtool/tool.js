$(document).ready(function () {
    let storage = window.localStorage;

    // populate form with locally cached values
    let fields = ["auth.bearer_token"];
    for (field in fields) {
        field = fields[field]
        let value = storage.getItem('twitter.' + field);
        if (typeof value != 'undefined' && value !== 'undefined') {
            $('#twitter-' + field).val(value);
        }
    }

    // todo: not break submitting if user changes to other data source
    $('#query-form').off('submit');
    $('#query-form.parler').on('submit', function (e) {
        e.preventDefault();
        let token = $('#twitter-auth.bearer_token').val();

        // locally cache input values
        storage.setItem('twitter.auth.bearer_token', token);

        query.start();
        return false;
    })
});