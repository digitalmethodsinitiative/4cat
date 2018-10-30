//AJAX functions that retrieve user input and send it to the server so Python can do it's magic
$(function() {

	// global variables
	var loadedcsv = {}
	var obj_jsonimages = {}
	var timeout
	var query_key = null

	function start_query(){

		// Show loader
		$('.loader').show()

		// Get AJAX url from search options
		ajax_url = get_ajax_url()
		console.log(ajax_url)

		// AJAX the query to the server
		$.ajax({
			dataType: "text",
			url: ajax_url,
			success: function(response) {
				console.log(response);

				// If the query is rejected by the server.
				if (response.substr(0, 14) == 'Invalid query.') {
					$('.loader').hide()
					alert(response)
				}

				// If the query is accepted by the server.
				else{
					query_key = response
					poll_csv(query_key)

					// poll results every 2000 ms after submitting
					poll_interval = setInterval(function() {
						poll_csv(query_key);
					}, 4000);
				}
			},
			error: function(error) {
				console.log('error')
				console.log(error);
				$('#results').html('<h3>' +$('#dataselection option:selected').text() + " error</h3>")
				$('.loader').hide()
			}
		});
	}
	
	function poll_csv(query_key){
		/*
		Polls server to check whether there's a result for query
		*/
		$.ajax({
			dataType: "text",
			url: 'check_query/' + query_key,
			success: function(response) {
				console.log(response)

				// if the server hasn't processed the query yet, do nothing
				if (response == 'no_file') {
					// do nothing
				}

				// if there are no results in the database, notify user
				else if (response == 'empty_file') {
					clearInterval(poll_interval)
					$('.loader').hide()
					alert('No results for your search input.\nPlease edit search.')
				}

				// if the query succeeded, notify user
				else {
					clearInterval(poll_interval)
					$('#submitform').append('<a href="' + response + '"><p>' + response + '</p></a>')
					$('.loader').hide()
					alert('Query for \'' + response + '\' complete!')
				}
			},
			error: function(error) {
				console.log('Something went wrong when checking query status')
			}
		});
	}

	function get_ajax_url(){
		/*
		Takes the user input and generates an AJAX URL to send to Flask back-end
		Returns an error if not enough parameters are provided.
		*/

		// Set string parameters. Replace some potentially harmful characters.
		// Text in between * characters indicate exact match searches
		var url_body = $('#body-input').val().replace(/\"/g,"*");
		var url_subject = $('#subject-input').val().replace(/\"/g,"*");
		url_body = url_body.replace(/[^\p{L}A-Za-z0-9_*-]+/g,"-");
		url_subject = url_subject.replace(/[^\p{L}A-Za-z0-9_*-]+/g,"-");
		if(url_body == ''){url_body = 'empty'}
		if(url_subject == ''){url_subject = 'empty'}

		// Set full thread search parameter
		var url_full_thread
		if($('#check-full-thread').is(':checked') && url_body !== ''){url_full_thread = 1}
		else{url_full_thread = 0}

		// Set keyword-dense threads parameters
		var url_dense_threads = 0
		var url_dense_percentage = 0
		var url_dense_thread_length = 0
		if($('#check-dense-threads').is(':checked') && url_body !== ''){
			url_dense_threads = 1
			url_dense_percentage = $('#dense-percentage').val()
			url_dense_thread_length = $('#dense-thread-length').val()
		}

		// Set time parameters
		var url_min_date = 0
		var url_max_date = 0
		if($('#check-time').is(':checked')){
			var min_date = $('#input-min-time').val()
			var max_date = $('#input-max-time').val()
			if (isNaN(min_date)){url_min_date = (new Date(min_date).getTime() / 1000)}
			if (isNaN(max_date)){url_max_date = (new Date(max_date).getTime() / 1000)}
		}
	
		// Create AJAX url
		ajax_url = 'string_query/' + url_body + '/' + url_subject + '/' + url_full_thread + '/' + url_dense_threads + '/' + url_dense_percentage + '/' + url_dense_thread_length + '/' + url_min_date + '/' + url_max_date

		return ajax_url
	}

	/* BUTTON EVENT HANDLERS */

	// Start querying when go button is clicked
	$('#btn_go').bind('click', function(){
		start_query()
	});

	// Run query when return is pressed
	$('input').keyup(function(e){ 
		var code = e.which;
		if(code==13)e.preventDefault();
		if(code==13||code==188||code==186){
			$("#btn_go").click();
		}
	});

	// Enable date selection when 'filter on time' checkbox is checked
	$('#check-time').on('change', function(){
		if(this.checked){$('.input-time').attr('disabled', false)}
		else{$('.input-time').attr('disabled', true)}
	});

	// Change the option and label for keyword-dense threads according to body input
	$('#body-input').on('input', function(){
		input_string = $('#body-input').val()
		if (input_string == ''){
			$('.density-keyword').html('keyword')
			$('.input-dense').prop('disabled', true)
			$('#check-keyword-dense-threads').prop('checked', false)
		}
		else{
			$('.input-dense').prop('disabled', false)
			if (input_string.length > 7){
				$('.density-keyword').html(input_string.substr(0,4) + '...')
			}
			else{
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
});