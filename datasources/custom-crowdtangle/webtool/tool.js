fourcat = {
    init: function() {
        $('#datasource-form').parents('form').attr('enctype', 'multipart/form-data');
    }
};

$(document).ready(fourcat.init);