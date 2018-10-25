//AJAX functions that retrieve user input and send it to the server so Python can do it's magic
$(function() {

	// hide the loading notification
	$('.loader').hide()

	$('#dataselection').change(function(){
		console.log(this)
		selectedcsv = ($(this).find(":selected").val())
		console.log(selectedcsv)

	});

	var loadedcsv = {}
	var obj_jsonimages = {}

	var column_comment			//columns have different names for different data sheets
	var column_author
	var column_createdtime
	var column_imagelink
	var column_score
	var column_threadnumber
	var column_country
	var column_subreddit
	var column_id
	var column_parent_id
	var platformselected = ''
	var timeout

	$('#btn_go').bind('click', function(){
		$('.loader').show()


		// query string is what's in the search box
		search_query = $('#searchinput').val()
		ajax_url = 'string_query/' + search_query

		if($('#check_time').is(':checked')){
			mindate = $('#input_mintime').val()
			mindate = (new Date(mindate).getTime() / 100)
			maxdate = $('#input_maxtime').val()
			maxdate = (new Date(maxdate).getTime() / 100)
			console.log(mindate, maxdate)
			ajax_url = ajax_url + '/' + mindate + '/' + maxdate
		}

		$.ajax({
			dataType: "text",
			url: 'string_query/' + search_query,
			success: function(response) {
				console.log(response);

				pollCsv(search_query)

				// poll every 2000 ms
				poll_interval = setInterval(function() {
					pollCsv(search_query);
				}, 2000);
			},
			error: function(error) {
				console.log('error')
				console.log(error);
				$('#results').html('<h3>' +$('#dataselection option:selected').text() + " error</h3>")
				$('.loader').hide()
			}
		});
	});
	
	function pollCsv(str_query){
		/*
		Polls server to check whether there's already a csv for a query
		*/
		$.ajax({
			dataType: "text",
			url: 'check_query/' + str_query,
			success: function(response) {
				console.log(response)

				// if the server hasn't processed the query yet, do nothing
				if (response == 'nofile') {
					// do nothing
				}

				// if there are no results in the database, notify user
				else if (response == 'empty_file') {
					clearInterval(poll_interval)
					$('.loader').hide()
					alert('No results for \'' + str_query + '\'.\nPlease edit search term.')
				}

				// if the query succeeded, notify user
				else {
					clearInterval(poll_interval)
					$('#submitform').append('<a href="http://' + location.hostname + '/fourcat/' + response + '"<p>mentions_' + search_query + '.csv</p></a>')
					$('.loader').hide()
					alert('Query for \'' + str_query + '\' complete!')
				}
			},
			error: function(error) {
				console.log('Something went wrong when checking query status')
			}
		});
	}
});