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

		// Set parameters
		var url_post = $('#body_input').val()
		var url_subject = $('#subject_input').val()
		var url_full_thread = $('#check-full-thread').attr('checked')?true:false;
		var url_min_date = 0
		var url_max_date = 0

		if(url_post == ''){url_post = '-'}
		if(url_subject == ''){url_subject = '-'}

		// Get time values
		if($('#check_time').is(':checked')){
			url_min_date = $('#input_mintime').val()
			url_max_date = $('#input_maxtime').val()
			url_min_date = (new Date(url_min_date).getTime() / 100)
			url_max_date = (new Date(url_max_date).getTime() / 100)
		}

		ajax_url = 'string_query/' + url_search_query + '/' + url_full_thread + '/' + url_min_date + '/' + url_max_date

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
					$('#submitform').append('<a href="' + response + '"><p>mentions_' + search_query + '.csv</p></a>')
					$('.loader').hide()
					alert('Query for \'' + str_query + '\' complete!')
				}
			},
			error: function(error) {
				console.log('Something went wrong when checking query status')
			}
		});
	}

	// start querying when go button is clicked
	$('#btn_go').bind('click', function(){
		start_query()
	});

	// run query when return is pressed
	$('input').keyup(function(e){ 
		var code = e.which;
		if(code==13)e.preventDefault();

		if(code==32||code==13||code==188||code==186){
			$("#btn_go").click();
		}
	});
});