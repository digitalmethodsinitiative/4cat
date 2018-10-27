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

		// Set string parameters
		var url_body = $('#body_input').val()
		var url_subject = $('#subject_input').val()
		if(url_body == ''){url_body = 'empty'}
		if(url_subject == ''){url_subject = 'empty'}
		
		// Set full thread search parameter
		var url_full_thread
		if($('#check-full-thread').is(':checked')){url_full_thread = 1}
		else{url_full_thread = 0}

		// Set time parameters
		var url_min_date = 0
		var url_max_date = 0
		if($('#check-time').is(':checked')){
			url_min_date = $('#input-min-time').val()
			url_max_date = $('#input-max-time').val()
			url_min_date = (new Date(url_min_date).getTime() / 1000)
			url_max_date = (new Date(url_max_date).getTime() / 1000)
		}

		// Create AJAX url
		ajax_url = 'string_query/' + url_body + '/' + url_subject + '/' + url_full_thread + '/' + url_min_date + '/' + url_max_date

		// AJAX the query to the server
		$.ajax({
			dataType: "text",
			url: ajax_url,
			success: function(response) {
				console.log(response);
				query_key = response
				poll_csv(query_key)

				// poll results every 2000 ms after submitting
				poll_interval = setInterval(function() {
					poll_csv(query_key);
				}, 4000);
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

	/* BUTTON EVENT HANDLERS */

	// Start querying when go button is clicked
	$('#btn_go').bind('click', function(){
		start_query()
	});

	// Run query when return is pressed
	$('input').keyup(function(e){ 
		var code = e.which;
		if(code==13)e.preventDefault();

		if(code==32||code==13||code==188||code==186){
			$("#btn_go").click();
		}
	});

	// Enable date selection when 'filter on time' checkbox is checked
	$('#check-time').on('change', function(){
		if(this.checked){$('.input-time').attr('disabled', false)}
		else{$('.input-time').attr('disabled', true)}
	});
});