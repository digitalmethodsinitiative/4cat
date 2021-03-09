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

    $('#datasource-form').on('change', 'input.input-time', function () {
        // convert date to unix timestamp
        // should this be done server-side instead...?
        let date = $(this).val().replace(/\//g, '-').split('-'); //allow both slashes and dashes
        let input_id = 'input[name=' + $(this).attr('name').split('_').slice(0, -1).join('_') + ']';

        if (date.length !== 3) {
            // need exactly 3 elements, else it's not a valid date
            $(input_id).val(0);
            $(this).val(null);
            return;
        }

        // can be either yyyy-mm-dd or dd-mm-yyyy
        if (date[0].length === 4) {
            date = date.reverse();
            $(this).val(date[2] + '-' + date[1] + '-' + date[0]);
        } else {
            $(this).val(date[0] + '-' + date[1] + '-' + date[2]);
        }

        // store timestamp in hidden 'actual' input field
        let date_obj = new Date(parseInt(date[2]), parseInt(date[1]) - 1, parseInt(date[0]));
        let timestamp = Math.floor(date_obj.getTime() / 1000);

        if (isNaN(timestamp)) {
            // invalid date
            $(this).val(null);
            $(input_id).val(0);
        } else {
            $(input_id).val(timestamp);
        }
    });
});