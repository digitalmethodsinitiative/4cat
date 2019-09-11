fourcat = {
    init: function() {
        $('.dense-element').hide();
        $('.sample-element').hide();
        
        $('#datasource-form #body-input').on('keyup', function() {
            value = $(this).val();
            if(!value) {
                value = 'Keyword';
            } else {
                value = '"' + value + '"';
            }

            $('#datasource-form .body-query').text(value);
        });

        $('#datasource-form #search-scope').on('change', function() {
           if($(this).val() != 'dense-threads') {
               $('#datasource-form .dense-element').prop('disabled', true);
               $('#datasource-form .dense-element').hide();
           } else {
               $('#datasource-form .dense-element').prop('disabled', false);
               $('#datasource-form .dense-element').show();
           }

           if($(this).val() != 'random-sample') {
               $('#datasource-form .sample-element').prop('disabled', true);
               $('#datasource-form .sample-element').hide();
           } else {
               $('#datasource-form .sample-element').prop('disabled', false);
               $('#datasource-form .sample-element').show();
           }
        });

        $('#datasource-form').on('change', 'input.input-time', function() {
            // convert date to unix timestamp
            // should this be done server-side instead...?
            let date = $(this).val().replace(/\//g, '-').split('-'); //allow both slashes and dashes
            let input_id = 'input[name=' + $(this).attr('name').split('_').slice(0, -1).join('_') + ']';

            if(date.length !== 3) {
                // need exactly 3 elements, else it's not a valid date
                $(input_id).val(0);
                $(this).val(null);
                return;
            }

            // can be either yyyy-mm-dd or dd-mm-yyyy
            if(date[0].length === 4) {
                date = date.reverse();
                $(this).val(date[2] + '-' + date[1] + '-' + date[0]);
            } else {
                $(this).val(date[0] + '-' + date[1] + '-' + date[2]);
            }

            // store timestamp in hidden 'actual' input field
            let date_obj = new Date(parseInt(date[2]), parseInt(date[1]) - 1, parseInt(date[0]));
            let timestamp = Math.floor(date_obj.getTime() / 1000);

            if(isNaN(timestamp)) {
                // invalid date
                $(this).val(null);
                $(input_id).val(0);
            } else {
                $(input_id).val(timestamp);
            }
        });
    }
};

$(document).ready(fourcat.init);