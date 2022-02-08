$(document).ready(function () {
    console.log('ok');
    $('#forminput-data-url').parent().addClass('hidden');

    // starting a telegram query is a little more involved than simply
    // submitting the parameters and waiting for the result; we need
    // to confirm our API credentials first
    $('#forminput-platform').on('change', function (e) {
        let platform = $('#forminput-platform').val();

        if(platform === 'tiktok-trex') {
            $('#forminput-data-url').parent().removeClass('hidden');
            $('#forminput-data-upload').val('');
            $('#forminput-data-upload').parent().addClass('hidden');
        } else {
            $('#forminput-data-url').parent().addClass('hidden');
            $('#forminput-data-upload').parent().removeClass('hidden');
        }
    })
});