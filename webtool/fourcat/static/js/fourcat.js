var dot_ticker = 0;

//AJAX functions that retrieve user input and send it to the server so Python can do it's magic
$(function() {
    setInterval(update_query_statuses, 4000);

	// global variables
	var loadedcsv = {}
	var obj_jsonimages = {}
	var timeout
	var query_key = null

	function start_query(){

		// Show loader
		$('.loader').show()

		//check form input
		if(!validate_form()) {
			$('.loader').hide()
			return;
		}

		let formdata = $('#query-form').serialize();

        // AJAX the query to the server
        $.post({
            dataType: "text",
            url: "/queue-query/",
            data: formdata,
            success: function (response) {
                console.log(response);

                // If the query is rejected by the server.
                if (response.substr(0, 14) === 'Invalid query.') {
                    $('.loader').hide()
                    alert(response);
                    $('#query_status .status_message .message').html(response);
                    $('#whole-form').removeAttr('disabled');
                }

                // If the query is accepted by the server.
                else {
                    $('#query_status .status_message .message').html('Query submitted, waiting for results');
                    query_key = response
                    poll_csv(query_key)

                    // poll results every 2000 ms after submitting
                    poll_interval = setInterval(function () {
                        poll_csv(query_key);
                    }, 4000);
                }
            },
            error: function (error) {
                $('#query_status .status_message .message').html(error);
                $('#whole-form').removeAttr('disabled');
                console.log(error);
                $('#results').html('<h3>' + $('#dataselection option:selected').text() + " error</h3>")
                $('.loader').hide()
            }
        });

	}
	
	function poll_csv(query_key){
		/*
		Polls server to check whether there's a result for query
		*/
		$.getJSON({
			url: 'check_query/' + query_key,
			success: function(json) {
				console.log(json);

				let status_box = $('#query_status .status_message .message');
				let current_status = status_box.html();

				if(json.status !== current_status && json.status !== "") {
					status_box.html(json.status);
				}

				if(json.done) {
					clearInterval(poll_interval);
					let keyword = $('#body-input').val();
					if(keyword === '') {
						keyword = $('#subject-input').val();
					}

					$('#submitform').append('<a href="/results/' + json.key + '"><p>' + json.query + ' (' + json.rows + ' posts)</p></a>')
					$('.loader').hide();
					$('#query_status .status_message .dots').html('');
					$('#whole-form').removeAttr('disabled');
					alert('Query for \'' + keyword + '\' complete!');
				} else {
					let dots = '';
					for(let i = 0; i < dot_ticker; i+= 1) {
						dots += '.';
					}
					$('#query_status .status_message .dots').html(dots);

					dot_ticker += 1;
					if(dot_ticker > 3) {
						dot_ticker = 0;
					}
				}
			},
			error: function(error) {
				console.log('Something went wrong when checking query status')
			}
		});
	}

	function validate_form(){
		/*
		Checks validity of input; this is just a preliminary check, further checks are
		done server-side.
		*/

		var valid = true;

		if($('#check-time').is(':checked')){
			var min_date = $('#input-min-time').val()
			var max_date = $('#input-max-time').val()

			// Convert the minimum date string to a unix timestamp
			if (min_date !== '') {
				url_min_date = stringToTimestamp(min_date)

				// If the string was incorrectly formatted (could be on Safari), a NaN was returned
				if (isNaN(url_min_date)) {
					valid = false
					alert('Please provide a minimum date in the format dd-mm-yyyy (like 29-11-2017).')
				}
			}

			// Convert the maximum date string to a unix timestamp
			if (max_date !== '' && valid) {
				url_max_date = stringToTimestamp(max_date)
				// If the string was incorrectly formatted (could be on Safari), a NaN was returned
				if (isNaN(url_max_date)) {
					valid = false
					alert('Please provide a maximum date in the format dd-mm-yyyy (like 29-11-2017).')
				}
			}

			// Input can be ill-formed, like '01-12-90', resulting in negative timestamps
			if (url_min_date < 0 || url_max_date < 0 && valid) {
				valid = false
				alert('Invalid date(s). Check the bar on top with details on date ranges of 4CAT data.')
			}

			// Make sure the first date is later than or the same as the second
			if (url_min_date >= url_max_date && url_min_date !== 0 && url_max_date !== 0 && valid) {
				valid = false
				alert('The first date is later than or the same as the second.\nPlease provide a correct date range.')
			}
		}

		return valid;
	}

	/* BUTTON EVENT HANDLERS */

	// Start querying when go button is clicked
	$('#query-form').bind('submit', function(e){
		e.preventDefault();
		start_query();
		$('#whole-form').attr('disabled', 'disabled');
	});

	// Enable date selection when 'filter on time' checkbox is checked
	$('#check-time').on('change', function(){
		if (this.checked) {
			$('.input-time').attr('disabled', false)
		}
		else {
			$('.input-time').attr('disabled', true)
		}
	});

	// Change the option and label for keyword-dense threads according to body input
	$('#body-input').on('input', function(){
		input_string = $('#body-input').val()

		if (input_string == '') {
			$('.density-keyword').html('keyword')
			$('.input-dense').prop('disabled', true)
			$('#check-keyword-dense-threads').prop('checked', false)
		}
		else {
			$('.input-dense').prop('disabled', false)
			if (input_string.length > 7) {
				$('.density-keyword').html(input_string.substr(0,4) + '...')
			}
			else {
				$('.density-keyword').html(input_string)
			}
		}
	});

	// Only enable full thread data option if subject is queried
	$('#subject-input').on('input', function(){
		if ($(this).val() == ''){
			$('#check-full-thread').prop('disabled', true)
			$('#check-full-thread').prop('checked', false)
		}
		else{
			$('#check-full-thread').prop('disabled', false)
		}
	});

	$('.input-dense').prop('disabled', true)
	$('#check-full-thread').prop('disabled', true)
	$('body').on('click', '.result-list .postprocessor-link', function(e) {
		e.preventDefault();
		popup_panel.show($(this).attr('href'));
	});

	$('body').on('click', '#popup-panel .postprocessor-list a', function(e) {
		e.preventDefault();

		$(this).addClass('loading');
		$.post($(this).attr('href') + "?async=yes").done(function(response) {
			popup_panel.refresh();
		}).fail(function(response, code) {
			if(code === 403) {
				alert('The post-processor could not be queued because it is in the queue already. Refresh the page to see its status.')
			} else {
				alert('The post-processor could not be queued to to a server error. Please try again later, or contact a system administrator if the error persists.');
			}
		});
	})

	$('.result-list > li').each(function() {
		if(parseInt($(this).attr('data-numrows')) > 0) {
            $(this).append('<div><a class="button-like postprocessor-link" href="/results/' + $(this).attr('id') + '/postprocessors/">Analysis</a></div>');
        }
	})

	$('.view-controls button').hide();
	$('.view-controls input, .view-controls select, .view-controls textarea').on('change', function() {
		$(this).parents('form').trigger('submit');
	})
});

function datepicker_normalize() {
	let name = $(this).attr('name');
	let actual_name = name.split('_str').shift();
	let field = $('input[name=' + actual_name + ']');

	//create "normalized" form field if it doesn't exist already
	if(field.length === 0) {
		let form = $(this).parents('form')[0];
		console.log(form);
		field = $('<input type="hidden" name="' + actual_name + '" value="0">');
		field.appendTo(form);
	}

	field.val(stringToTimestamp($(this).val()));
}

function stringToTimestamp(str) {
	// Converts a text input to a unix timestamp.
	// Only used in Safari (other browsers use native HTML date picker)
	var date_regex = /^\d{4}-\d{2}-\d{2}$/
	if (str.match(date_regex)) {
		timestamp = (new Date(str).getTime() / 1000)
	}
	else {
		str = str.replace(/\//g,'-')
		str = str.replace(/\s/g,'-')
		var date_objects = str.split('-')
		var year = date_objects[2]
		var month = date_objects[1]
		// Support for textual months
		var testdate = Date.parse(month + "1, 2012");
		if(!isNaN(testdate)){
			month = new Date(testdate).getMonth() + 1;
		}
		var day = date_objects[0]
		timestamp = (new Date(year, (month - 1), day).getTime() / 1000)
	}
	return timestamp
}

popup_panel = {
	panel: false,
	blur: false,
	wrap: false,
	url: '',

	show: function(url, fade=true) {
		popup_panel.url = url;
		if(!popup_panel.blur) {
			popup_panel.blur = $('<div id="popup-blur"></div>');
			popup_panel.blur.on('click', popup_panel.hide);
			$('body').append(popup_panel.blur);
		}

		if(!popup_panel.panel) {
			popup_panel.panel = $('<div id="popup-panel"><div class="popup-wrap"></div></div>');
			popup_panel.wrap = popup_panel.panel.find('.popup-wrap');
			$('body').append(popup_panel.panel);
		}

		if(fade) {
            popup_panel.panel.addClass('loading');
            popup_panel.wrap.html('');
            popup_panel.panel.removeClass('closed').addClass('open');
            popup_panel.blur.removeClass('closed').addClass('open');
        }

		$.get(url).done(function(html) {
			popup_panel.wrap.animate({opacity:1}, 250);
			popup_panel.panel.removeClass('loading');
			popup_panel.wrap.html(html);
		}).fail(function(html, code) {
			alert('The page could not be loaded (HTTP error ' + code + ').');
			popup_panel.hide();
        });
	},

	refresh: function() {
		popup_panel.wrap.animate({opacity:0}, 250, function() {
			popup_panel.show(popup_panel.url, false);
		});
	},

	hide: function() {
		popup_panel.panel.removeClass('open').addClass('closed');
		popup_panel.blur.removeClass('open').addClass('closed');
	}
};

/**
 * Fancy live-updating subquery status
 *
 * Checks if running subqueries have finished, updates their status, and re-enabled further
 * analyses if all subqueries have finished
 */
function update_query_statuses() {
    let queued = $('.running.subquery');
    if(queued.length === 0) {
        return;
    }

    let keys = new Array();
    queued.each(function() {
        keys.push($(this).attr('id').split('-')[1])
    });

    $.get({
        url: "/check_postprocessors/",
        data: {subqueries: JSON.stringify(keys)},
        success: function(json) {
            json.forEach(subquery => {
                let selector = '#subquery-' + subquery.key;
                if($(selector).length === 0) {
                    selector = '#subquery-job' + subquery.job;
                }
                let li = $(selector);
                let old_status = li.html();
                li.replaceWith(subquery.html);

                li = $('#subquery-' + subquery.key);
                if(li.html() == old_status) {
                    return;
                }


                li.addClass('flashing');
                if(!$('body').hasClass('result-page')) {
                    return;
                }

                if($('.running.subquery').length == 0) {
                    $('.result-warning').animate({height: 0}, 250, function() { $(this).remove(); });
                    $('.queue-button-wrap').removeClass('hidden');
                }
            });
        }
    })
}