var dot_ticker = 0;
var timeout;
var query_key = null;
var poll_interval;

/**
 * Page init
 */

$(init);

function init() {
	// Check status of query
	if($('body.result-page').length > 0) {
		query.update_status();
		setInterval(query.update_status, 4000);

		// Check processor queue
		query.check_processor_queue();
		setInterval(query.check_processor_queue, 10000);
	}

	// Check search queue
	if($('#query-form').length > 0) {
		query.check_search_queue();
		setInterval(query.check_search_queue, 10000);
	}

	//regularly check for unfinished datasets
	setInterval(query.check_resultpage, 2000);

	// Update dynamic containers
	setInterval(dynamic_container.refresh, 2500);

	// Start querying when go button is clicked
	$('#query-form').on('submit', function (e) {
		e.preventDefault();
		query.start();
	});

	// Data source select boxes trigger an update of the boards available for the chosen data source
	$('#datasource-select').on('change', query.update_form);
	$('#datasource-select').trigger('change');

	// Special cases in dataset entry form
	$('#datasource-form').on('change', 'input[type=date]', query.proxy_dates);
	$('#datasource-form').on('change', '#forminput-search_scope', query.handle_density);
	$('#datasource-form').on('change', '#forminput-board', query.custom_board_options);

	// Controls to change which results show up in overview
	$('.view-controls button').hide();
	$('.view-controls input, .view-controls select, .view-controls textarea').on('change', function () {
		$(this).parents('form').trigger('submit');
	});

	//expand/collapse
	$(document).on('click', '.toggle-button', toggleButton);
	$(document).on('click', '#expand-datasets', toggleDatasets);

	//tooltips
	$(document).on('mousemove', '.tooltip-trigger', tooltip.show);
	$(document).on('mouseout', '.tooltip-trigger', tooltip.hide);
	$(document).on('click', '.tooltip-trigger', tooltip.toggle);

	//popups
	$(document).on('click', '.popup-trigger', popup.show);

	// child of child of child etc interface bits
	$(document).on('click', '.processor-queue-button', processor.queue);

	// dataset deletion
	$(document).on('click', '.delete-link', processor.delete);

	// dataset label edit
	$('.result-page .card h2').each(query.label.init);
	$(document).on('click', '.edit-dataset-label', query.label.handle);
	$(document).on('keydown', '#new-dataset-label', query.label.handle);

	//allow opening given analysis path via anchor links
	navpath = window.location.hash.substr(1);
	if (navpath.substring(0, 4) === 'nav=') {
		let analyses = navpath.substring(4).split(',');
		let navigate = setInterval(function () {
			if (analyses.length === 0) {
				clearInterval(navigate);
				return;
			}
			let breadcrumb = analyses.shift();
			if (analyses.length === 0) {
				$('.anchor-child').removeClass('anchor-child');
				$('#child-' + breadcrumb).addClass('anchor-child');
			}
			$('#child-' + breadcrumb + ' > .processor-expand > button').trigger('click');
		}, 25);
	}

	// Notify that dense threads can only be selected if a body string is provided
	$('#dense-threads-filterlabel').on('click', function(){
		if ($('#body-input').val().length == 0) {
			alert('Please provide a keyword in the post body field.');
			$('#body-input').focus();
			$('#body-input').select;
		}
	});

	// Multichoice inputs need to be loaded dynamically
	$(document).on('click', '.toggle-button', function(){
		if ($(".multichoice-wrapper, .multi-select-wrapper").length > 0) {
			makeMultichoice();
		}
	});

	// Remove multichoice select labels and input when clicked
	$(document).on('click', '.multi-select-selected > span', function(){

		let name = $(this).attr("name");
		let val = $(this).val();
		let current_select = $(".multi-select-input[name='" + name.split(":")[0] + "']")
		let replace_input = current_select.val().replace(val + ",", "").replace(val, "");

		current_select.val(replace_input);

		$(".multi-select-options input[name='" + name + "']").prop("checked", false);

		$(this).remove();
	});

	//confirm links
	$(document).on('click', '.confirm-first', function(e) {
		let action = 'do this';

		if($(this).attr('data-confirm-action')) {
			action = $(this).attr('data-confirm-action');
		}

		if(!confirm('Are you sure you want to ' + action + '? This cannot be undone.')) {
			e.preventDefault();
			return false;
		} else {
			return true;
		}
	});

	//long texts with '...more' link
	$(document).on('click', 'div.expandable a', function(e) {
		e.preventDefault();

		if($(this).text() == '...more') {
			$(this).text('...less');
			$(this).parent().find('.sr-only').removeClass('sr-only').addClass('expanded');
		} else {
			$(this).text('...more');
			$(this).parent().find('.expanded').addClass('sr-only').removeClass('expanded');
		}
	});
	$('.has-more').each(function() {
		let max_length = parseInt($(this).attr('data-max-length'));
		let full_value = $(this).text();
		if(full_value.length < max_length) {
			return;
		}
		$(this).replaceWith('<div class="expandable">' + full_value.substring(0, max_length) + '<span class="sr-only">' + full_value.substring(max_length) + '</span><a href="#">...more</a></div>');
	});
}

/**
 * Post-processor handling
 */
 processor = {
	/**
	 * Queue a post-processor
	 *
	 * Submit parameters and update result tree with new item if added
	 *
	 * @param e  Event that triggered queueing
	 */
	 queue: function (e) {
		e.preventDefault();

		if ($(this).text().includes('Run')) {
			let form = $(this).parents('form');
			let position = form.position().top + parseInt(form.height());

			// if it's a big dataset, ask if the user is *really* sure
			let parent = $(this).parents('li.child-wrapper');
			if(parent.length == 0) {
				parent = $('.result-tree');
			}
			let num_rows = parseInt($('#dataset-' + parent.attr('data-dataset-key') + '-result-count').attr('data-num-results'));

			if(num_rows > 500000) {
				if(!confirm('You are about to start a processor for a dataset with over 500,000 items. This may take a very long time and block others from running the same type of analysis on their datasets.\n\nYou may be able to get useful analysis results with a smaller dataset instead. Are you sure you want to start this analysis?')) {
					return;
				}
			}

			$.ajax(form.attr('data-async-action') + '?async', {
				'method': form.attr('method'),
				'data': form.serialize(),
				'success': function (response) {
					if (response.messages.length > 0) {
						alert(response.messages.join("\n\n"));
					}

					if (response.html.length > 0) {
						let new_element = $(response.html);
						let container_id = response.container + ' .child-list';

						let parent_list = $($(container_id)[0]);

						// this is hardcoded, see next comment

						let targetHeight = 68;
						// the position of the newly inserted element is always 0 for some reason
						// so we use the fact that it's inserted at the bottom of the source_dataset to
						// infer it
						let position = parent_list.offset().top + parent_list.height() - (targetHeight * 2);

						let viewport_top = $(window).scrollTop();
						let viewport_bottom = viewport_top + $(window).height();
						new_element.appendTo($(parent_list));
						new_element = $('body #' + new_element.attr('id'));
						new_element.css('height', '0px').css('border-width', '0px').css('opacity', 0);

						let expand = function() {
							new_element.animate({'height': targetHeight, 'opacity': 1}, 500, false, function() { $(this).css('height', '').css('opacity', '').css('border-width', ''); });
						}

						if(position < viewport_top || position > viewport_bottom) {
							$('html,body').animate({scrollTop: position + 'px'}, 500, false, expand);
						} else {
							expand();
						}
					}
				},
				'error': function (response) {
					alert('The analysis could not be queued: ' + response.responseText);
				}
			});

			if($(this).data('original-content')) {
				$(this).html($(this).data('original-content'));
				$(this).trigger('click');
				$(this).html($(this).data('original-content'));
				form.trigger('reset');
			}
		} else {
			$(this).data('original-content', $(this).html());
			$(this).find('.byline').html('Run');
			$(this).find('.fa').removeClass('.fa-cog').addClass('fa-play');
		}
	},

	delete: function(e) {
		e.preventDefault();

		if(!confirm('Are you sure? Deleted data cannot be restored.')) {
			return;
		}

		$.ajax(getRelativeURL('api/delete-query/'), {
			method: 'DELETE',
			data: {key: $(this).attr('data-key')},
			success: function(json) {
				$('li#child-' + json.key).animate({height: 0}, 200, function() { $(this).remove(); });
				query.enable_form();
			},
			error: function(json) {
				alert('Could not delete dataset: ' + json.status);
			}
		});
	}
};

/**
 * Query queueing and updating
 */
query = {
	/**
	 * Enable query form, so settings may be changed
	 */
	enable_form: function() {
		$('#query-status .delete-link').remove();
		$('#query-status .status_message .dots').html('');
		$('#query-status .message').html('Waiting for input...');
		$('#query-form fieldset').prop('disabled', false);
		$('#query-status').removeClass('active');
	},

	/**
	 * Disable query form, while query is active
	 */
	disable_form: function() {
		$('#query-form fieldset').prop('disabled', true);
		$('#query-status').addClass('active');
	},

	/**
	 * Tool window: start a query, submit it to the backend
	 */
	start: function () {

		//check form input
		if (!query.validate()) {
			return;
		}

		// Show loader
		query.check_search_queue();

		let form = $('#query-form');
		let formdata = new FormData(form[0]);

		// Cache cacheable values
		let datasource = form.attr('class');
		form.find('.cacheable input').each(function() {
			let item_name = datasource + '.' + $(this).attr('name');
			let s = localStorage.setItem(item_name, $(this).val());
		})
		
		// Disable form
		query.disable_form();
		$('html,body').scrollTop(200);

		// AJAX the query to the server
		$('#query-status .message').html('Sending dataset parameters');
		$.post({
			dataType: "text",
			url: form.attr('action'),
			data: formdata,
			cache: false,
			contentType: false,
			processData: false,

			success: function (response) {

				// If the query is rejected by the server.
				if (response.substr(0, 14) === 'Invalid query.') {
					alert(response);
					query.enable_form();
				}

				// If the query is accepted by the server.
				else {
					$('#query-status .message').html('Query submitted, waiting for results');
					query_key = response;
					query.check(query_key);

					$('#query-status').append($('<button class="delete-link" data-key="' + query_key + '">Cancel</button>'));

					// poll results every 2000 ms after submitting
					poll_interval = setInterval(function () {
						query.check(query_key);
					}, 4000);
				}
			},
			error: function (error) {
				query.enable_form();
				$('#query-status .message').html(error);
			}
		});
	},

	/**
	 * After starting query, periodically check its status and link to result when available
	 * @param query_key  Key of started query
	 */
	check: function (query_key) {
		/*
		Polls server to check whether there's a result for query
		*/
		$.getJSON({
			url: getRelativeURL('api/check-query/'),
			data: {key: query_key},
			success: function (json) {
				query.check_search_queue();

				let status_box = $('#query-status .message');
				let current_status = status_box.html();

				if (json.status !== current_status && json.status !== "") {
					status_box.html(json.status);
				}

				if (json.done) {
					clearInterval(poll_interval);
					let keyword = json.label;

					$('#query-results').append('<li><a href="/results/' + json.key + '">' + keyword + ' (' + json.rows + ' items)</a></li>');
					query.enable_form();
					alert('Query for \'' + keyword + '\' complete!');
				} else {
					let dots = '';
					for (let i = 0; i < dot_ticker; i += 1) {
						dots += '.';
					}
					$('#query-status .dots').html(dots);

					dot_ticker += 1;
					if (dot_ticker > 3) {
						dot_ticker = 0;
					}
				}
			},
			error: function () {
				console.log('Something went wrong while checking query status');
			}
		});
	},

	check_resultpage: function() {
		let unfinished = $('.dataset-unfinished');
		if(unfinished.length === 0) {
			return;
		}

		$('.dataset-unfinished').each(function() {
			let container = $(this);
			$.getJSON({
				url: getRelativeURL('api/check-query/'),
				data: {key: $(this).attr('data-key')},
				success: function (json) {
					if (json.done) {
						//refresh
						window.location = window.location;
						return;
					}

					let current_status = container.find('.dataset-status').html();
					if (current_status !== json.status_html) {
						container.find('.dataset-status').html(json.status_html);
					}
				}
			});
		});
	},

	/**
	 * Fancy live-updating child dataset status
	 *
	 * Checks if running subqueries have finished, updates their status, and re-enabled further
	 * analyses if all subqueries have finished
	 */
	update_status: function () {
		if(!document.hasFocus()) {
			//don't hammer the server while user is looking at something else
			return;
		}

		let queued = $('.child-wrapper.running');
		if (queued.length === 0) {
			return;
		}

		let keys = [];
		queued.each(function () {
			keys.push($(this).attr('data-dataset-key'));
		});

		$.get({
			url: getRelativeURL('api/check-processors/'),
			data: {subqueries: JSON.stringify(keys)},
			success: function (json) {
				json.forEach(child => {
					let target = $('body #child-' + child.key);
					let update = $(child.html);
					update.attr('aria-expanded', target.attr('aria-expanded'));

					if (target.attr('data-status') === update.attr('data-status') && target.attr('class') === update.attr('class')) {
						console.log(target.attr('data-status'));
						return;
					}

					$('#dataset-results').html(child.resultrow_html);

					target.replaceWith(update);
					update.addClass('updated');
					target.remove();
				});
			}
		});
	},

	check_search_queue: function () {
		/*
		Polls server to check how many search queries are still in the queue
		*/
		if(!document.hasFocus()) {
			//don't hammer the server while user is looking at something else
			return;
		}

		$.getJSON({
			url: getRelativeURL('api/check-search-queue/'),
			success: function (json) {

				// Update the query status box with the queue status
				let search_queue_box = $('#search-queue-status .search-queue-message');
				let search_queue_list = $('#search-queue-status .search-queue-list');

				// To display in the search queue box
				let search_queue_length = 0
				let search_queue_notice = ""

				for(let i = 0; i < json.length; i += 1){
					search_queue_length += json[i]['count'];
					search_queue_notice += " <span class='property-badge'>" + json[i]['jobtype'].replace('-search','') + ' (' + json[i]['count'] + ')' + '</span>'
				}

				if (search_queue_length == 0) {
					search_queue_box.html('Search queue is empty.');
					search_queue_list.html('');
				}
				else if (search_queue_length == 1) {
					search_queue_box.html('Currently processing 1 search query: ');
					search_queue_list.html(search_queue_notice);
				}
				else {
					search_queue_box.html('Currently processing ' + search_queue_length + ' search queries: ');
					search_queue_list.html(search_queue_notice);
				}
			},
			error: function () {
				console.log('Something went wrong when checking search query queue');
			}
		});
	},

	check_processor_queue: function () {
		/*
		Checks what processors are in the queue and keeps updating the option/run buttons
		and already-queued processes buttons.
		*/
		if(!document.hasFocus()) {
			//don't hammer the server while user is looking at something else
			return;
		}
		
		$.getJSON({
			url: getRelativeURL('api/status.json'),
			success: function (json) {

				// Remove previous notices
				$(".queue-notice").html("");

				queued_processes = json["items"]["backend"]["queued"];

				// Loop through all running processors
				for (queued_process in queued_processes) {

					// The message to display
					let notice = json["items"]["backend"]["queued"][queued_process] + " in queue"

					// Add notice if this processor has a run/options button
					let processor_run = $('.processor-queue-button.' + queued_process + '-button');
					if ($(processor_run).length > 0){
						$('.processor-queue-button.' + queued_process + '-button > .queue-notice').html(notice);
					}

					// Add another notice to "analysis results" section if processor is pending
					let processor_started = $('.processor-result-indicator.' + queued_process + '-button');
					if ($(processor_started).length > 0){

						$('.processor-result-indicator.' + queued_process + '-button.queued-button > .button-object > .queue-notice').html(notice);
					}
				}
			},
			error: function (error) {
				console.log(error["responseText"])
				console.log('Something went wrong when checking 4CAT\'s status');
			}
		});
	},

	/**
	 * Validate query submission form
	 *
	 * @returns {boolean}  Whether the form is ready for submission
	 */
	validate: function () {
		/*
		Checks validity of input; this is just a preliminary check, further checks are
		done server-side.
		*/

		let valid = true;

		if ($('#check-time').is(':checked')) {
			let min_date = $('#input-min-time').val();
			let max_date = $('#input-max-time').val();
			let url_max_date;
			let url_min_date;

			// Convert the minimum date string to a unix timestamp
			if (min_date !== '') {
				url_min_date = stringToTimestamp(min_date);

				// If the string was incorrectly formatted (could be on Safari), a NaN was returned
				if (isNaN(url_min_date)) {
					valid = false;
					alert('Please provide a minimum date in the format dd-mm-yyyy (like 29-11-2017).');
				}
			}

			// Convert the maximum date string to a unix timestamp
			if (max_date !== '' && valid) {
				url_max_date = stringToTimestamp(max_date);
				// If the string was incorrectly formatted (could be on Safari), a NaN was returned
				if (isNaN(url_max_date)) {
					valid = false;
					alert('Please provide a maximum date in the format dd-mm-yyyy (like 29-11-2017).');
				}
			}

			// Input can be ill-formed, like '01-12-90', resulting in negative timestamps
			if (url_min_date < 0 || url_max_date < 0 && valid) {
				valid = false;
				alert('Invalid date(s). Check the bar on top with details on date ranges of 4CAT data.');
			}

			// Make sure the first date is later than or the same as the second
			if (url_min_date >= url_max_date && url_min_date !== 0 && url_max_date !== 0 && valid) {
				valid = false;
				alert('The first date is later than or the same as the second.\nPlease provide a correct date range.');
			}
		}

		// Country flag check
		if ($('#check-country-flag').is(':checked') && ($('#body-input').val()).length < 2 && valid) {
			
			let common_countries = ['US', 'GB', 'CA', 'AU'];
			let country = $('#country_flag').val();

			// Don't allow querying without date ranges for the common countries
			if (common_countries.includes(country)){
				if ($('#check-time').is(':checked')) {

					let min_date = stringToTimestamp($('#input-min-time').val());
					let max_date = stringToTimestamp($('#input-max-time').val());
					
					// Max three monhts for the common country flags without any body parameters
					if (max_date - min_date > 7889231) {
						valid = false;
						alert('The date selected is more than three months. Select a date range of max. three months and try again. Only the most common country flags on 4chan/pol/ (US, UK, Canada, Australia) have a date restriction.');
					}
				}
				else {
					valid = false;
					$('#check-time').prop('checked', true);
					$('#check-time').trigger('change');
					$('#input-min-time').focus().select();
					alert('The most common country flags on 4chan/pol/ (US, Canada, Australia) have a date restriction when you want to retreive all of their posts. Select a date range of max. three months and try again.');
				}
			}
		}

		// Return true if everyting is passed
		return valid;
	},

	/**
	 * Update board select list for chosen datasource
	 */
	update_form: function() {
		datasource = $('#datasource-select').val();
		$.get({
			'url': getRelativeURL('api/datasource-form/' + datasource + '/'),
			'success': function(data) {
				$('#query-form-script').remove();
				$('#query-form').removeClass();
				$('#query-form').addClass(datasource);
				$('#datasource-form').html(data.html);
				if(data.has_javascript) {
					$('<script id="query-form-script">').attr('src', getRelativeURL('api/datasource-script/' + data.datasource + '/')).appendTo('body');
				}
				//automatically fill in cached parameters
				$('#datasource-form .cacheable input').each(function() {
				   let item_name = datasource + '.' + $(this).attr('name');
				   let cached_value = localStorage.getItem(item_name);
				   if (typeof cached_value != 'undefined' && cached_value !== 'undefined') {
					   $(this).val(cached_value);
				   }
				});

				query.handle_density();
				query.custom_board_options();
                
                // Render custom multiple choice fields
                // should also be rendered dynamically if processor options are expanded.
                if ($('.multichoice-wrapper').length || $('.multi-select-wrapper').length) {
                    makeMultichoice();
                }
			},
			'error': function() {
				$('#datasource-select').parents('form').trigger('reset');
				alert('Invalid datasource selected.');
			}
		});
	},

	handle_density: function() {
		// datasources may offer 'dense thread' options
		// these are sufficiently generalised that they can be handled in this
		// main script...
		let scope = $('#query-form #forminput-search_scope').val()

		let dense_toggle = (scope === 'dense-threads');
		$('#query-form #forminput-scope_density').prop('disabled', !dense_toggle);
		$('#query-form #forminput-scope_density').parent().toggle(dense_toggle);
		$('#query-form #forminput-scope_length').prop('disabled', !dense_toggle);
		$('#query-form #forminput-scope_length').parent().toggle(dense_toggle);

		let ids_toggle = (scope === 'match-ids')
		$('#query-form #forminput-valid_ids').prop('disabled', !ids_toggle);
		$('#query-form #forminput-valid_ids').parent().toggle(ids_toggle);
	},

	custom_board_options: function() {
	// Some boards/subforums for datasources could have differing options.
	// Use this function to update these dynamically.
	// Board-specific fields can be added with `board_specific` in the datasource's Python configuration.

		let board = $('#forminput-board').val();
		let board_specific = '.form-element[data-board-specific]'

		if ($('.form-element[data-board-specific]').length > 0) {
			$(board_specific).hide();
			$(board_specific + ' input').val(null);
			$(board_specific + ' input').prop('checked', false);
			$(board_specific + ' .multi-select-selected').empty();
			$(board_specific).prop('disabled', true);
			$('.form-element[data-board-specific*="' + board +'"]').prop('disabled', false);
			$('.form-element[data-board-specific*="' + board +'"]').show();
		}
	},

	proxy_dates: function() {
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
	},

	label: {
		init: function() {
			$(this).append('<button class="edit-dataset-label"><i class="fa fa-edit"></i><span class="sr-only">Edit label</span></button>');
		},

		handle: function(e) {
			let button = $(this).parents('div').find('button');
			if(e.type == 'keydown' && e.keyCode != 13) { return; }

			if(button.find('i').hasClass('fa-check')) {
				query.label.save(e, button);
			} else {
				query.label.edit(e, button);
			}
		},

		edit: function(e, self) {
			e.preventDefault();
			let current = $(self).parent().find('span a');
			let field = $('<input id="new-dataset-label">');
			field.val(current.text());
			field.attr('data-url', current.attr('href'));
			current.replaceWith(field);
			field.focus().select();
			$(self).parent().find('i.fa').removeClass('fa-edit').addClass('fa-check');
		},

		save: function(e, self) {
			e.preventDefault();
			let field = $(self).parent().find('input');
			let new_label = field.val();
			let dataset_key = $('section.result-tree').attr('data-dataset-key')

			$.post({
				dataType: "json",
				url: '/api/edit-dataset-label/' + dataset_key + '/',
				data: {label: new_label},
				cache: false,

				success: function (json) {
					let link = $('<a href="' + json.url + '">' + json.label + '</a>');
					field.replaceWith(link);
					$(self).parent().find('i.fa').removeClass('fa-check').addClass('fa-edit');
				},
				error: function (response) {
					alert('Oh no! ' +response.text);
				}
			});
		}
	}
};


/**
 * Tooltip management
 */
 tooltip = {
	/**
	 * Show tooltip
	 *
	 * @param e  Event that triggered tooltip display
	 * @param parent  Element the toolip describes
	 */
	 show: function (e, parent = false) {
		if (e) {
			e.preventDefault();
		}
		if (!parent) {
			parent = this;
		}

		//determine target - last aria-controls value starting with 'tooltip-'
		let targets = $(parent).attr('aria-controls').split(' ');
		let tooltip_container = '';
		targets.forEach(function(target) {
			if(target.split('-')[0] === 'tooltip') {
				tooltip_container = target;
			}
		});
		tooltip_container = '#' + tooltip_container;

		if ($(tooltip_container).is(':hidden')) {
			$(tooltip_container).removeClass('force-width');
			let position = $(parent).position();
			let parent_width = parseFloat($(parent).css('width').replace('px', ''));
			$(tooltip_container).show();

			// figure out if this is a multiline tooltip
			content = $(tooltip_container).html();
			$(tooltip_container).html('1');
			em_height = $(tooltip_container).height();
			$(tooltip_container).html(content);
			if($(tooltip_container).height() > em_height) {
				$(tooltip_container).addClass('force-width');
			}

			let width = parseFloat($(tooltip_container).css('width').replace('px', ''));
			let height = parseFloat($(tooltip_container).css('height').replace('px', ''));
			$(tooltip_container).css('top', (position.top - height - 5) + 'px');
			$(tooltip_container).css('left', (position.left + (parent_width / 2) - (width / 2)) + 'px');
		}
	},

	/**
	 * Hide tooltip
	 *
	 * @param e  Event that triggered the toggle
	 * @param parent  Element the tooltip belongs to
	 */
	 hide: function (e, parent = false) {
		//determine target - last aria-controls value starting with 'tooltip-'
		if(!parent) {
			parent = this;
		}
		let targets = $(parent).attr('aria-controls');
		let tooltip_container = '';
		targets.split(' ').forEach(function(target) {
			if(target.split('-')[0] === 'tooltip') {
				tooltip_container = target;
			}
		});
		tooltip_container = '#' + tooltip_container;
		$(tooltip_container).hide();
	},
	/**
	 * Toggle tooltip between shown and hidden
	 * @param e  Event that triggered the toggle
	 */
	 toggle: function (e) {
		if(this.tagName.toLowerCase() !== 'a') {
			// Allow links to have tooltips and still work
			e.preventDefault();
		}

		let tooltip_container = $('#' + $(this).attr('aria-controls'));
		if ($(tooltip_container).is(':hidden')) {
			tooltip.show(e, this);
		} else {
			tooltip.hide(e, this);
		}
	}
};

/**
 * Popup management
 */
 popup = {
	/**
	 * Set up containers and event listeners for popup
	 */
	 is_initialised: false,
	 init: function() {
		$('<div id="blur"></div>').appendTo('body');
		$('<div id="popup"><div class="content"></div><button id="popup-close"><i class="fa fa-times" aria-hidden="true"></i> <span class="sr-only">Close popup</span></button></div>').appendTo('body');
		$('body').on('click', '#blur, #popup-close', popup.hide);
		popup.is_initialised = true;
	 },
	/**
	 * Show popup, using the content of a designated container
	 *
	 * @param e  Event
	 * @param parent  Parent, i.e. the button controlling the popup
	 */
	 show: function(e, parent) {
		if(!popup.is_initialised) {
			popup.init();
		}

		if (!parent) {
			parent = this;
		}

		if(e) {
			e.preventDefault();
		}

		//determine target - last aria-controls value starting with 'popup-'
		let targets = $(parent).attr('aria-controls').split(' ');
		let popup_container = '';
		targets.forEach(function(target) {
			if(target.split('-')[0] === 'popup') {
				popup_container = target;
			}
		});
		popup_container = '#' + popup_container;

		//copy popup contents into container
		$('#popup .content').html($(popup_container).html());
		$('#blur').attr('aria-expanded', true);
		$('#popup').attr('aria-expanded', true);

		$('#popup embed').each(function() {
			svgPanZoom(this, {contain: true});
		});
	},
	/**
	 * Hide popup
	 *
	 * @param e  Event
	 */
	 hide: function(e) {
		$('#popup .content').html('');
		$('#blur').attr('aria-expanded', false);
		$('#popup').attr('aria-expanded', false);
	 }
	};

/**
 * Dynamic panels
 */
 dynamic_container = {
	refresh: function() {
		if(!document.hasFocus()) {
			//don't hammer the server while user is looking at something else
			return;
		}

		$('.content-container').each(function() {
			let url = $(this).attr('data-source');
			let interval = parseInt($(this).attr('data-interval'));
			let previous = $(this).attr('data-last-call');
			if(!previous) {
				previous = 0;
			}

			let now = Math.floor(Date.now() / 1000);
			if((now - previous) < interval) {
				return;
			}

			let container = $(this);
			$.get({'url': url, 'success': function(response) {
				if(response === container.html()) {
					return;
				}
				container.html(response);
				container.attr('data-last-call', Math.floor(Date.now() / 1000));
			}, 'error': function() { container.attr('data-last-call', Math.floor(Date.now() / 1000)); }})
		});
	}
};

/** General-purpose toggle buttons **/
function toggleButton(e, force_close=false) {
	e.preventDefault();

	target = '#' + $(this).attr('aria-controls');
	
	is_open = $(target).attr('aria-expanded') !== 'false';
	if (is_open || force_close) {
		$(target).animate({'height': 0}, 250, function() { $(this).attr('aria-expanded', false).css('height', ''); });

		// Also collapse underlying panels that are still open
		$(target).find('*[aria-expanded=true]').attr('aria-expanded', false);
	} else {
		$(target).css('visibility', 'hidden').css('position', 'absolute').css('display', 'block').attr('aria-expanded', true);
		let targetHeight = $(target).height();
		$(target).css('aria-expanded', false).css('position', '').css('display', '').css('visibility', '').css('height', 0);
		$(target).attr('aria-expanded', true).animate({"height": targetHeight}, 250, function() { $(this).css('height', '')});
	}
}

function toggleDatasets(e) {
	let new_text;
	let expanded_state;

	if($(this).text().toLowerCase().indexOf('expand') >= 0) {
		new_text = 'Collapse all';
		expanded_state = true;
	} else {
		new_text = 'Expand all';
		expanded_state = false;
	}

	$(this).text(new_text);
	$('.processor-expand > button').each(function() {
		if($('#' + $(this).attr('aria-controls')).attr('aria-expanded')) {
			$('#' + $(this).attr('aria-controls')).attr('aria-expanded', expanded_state);
		}
	});
}

function makeMultichoice(){

	//more user-friendly select multiple
	$('.multichoice-wrapper').each(function() {

		let wrapper = $(this);
		let select = $(this).find('select');
		let name = select.attr('name');
		let input = $('<input type="hidden" name="' + name + '">');

		wrapper.append(input);

		select.find('option').each(function() {
			let selected = $(this).is(':selected');
			let checkbox_choice = $('<label><input type="checkbox" name="' + name + ':' + $(this).attr('value') + '"' + (selected?' checked="checked"':'') + '> ' + $(this).text() + '</label>');
			checkbox_choice.find('input').on('change', function() {
				let checked = wrapper.find('input:checked').map(function() {
					return $(this).attr('name').split(':')[1];
				}).get();
				input.val(checked.join(','));
			});
			wrapper.append(checkbox_choice);
		});
		select.remove();
	});

	// Multi-select choice menu requires some code.
	$('.multi-select-wrapper').each(function() {
		let wrapper = $(this);

		// do nothing if already expanded
		if (wrapper.find(".multi-select-input").length > 0) {
			return;
		}

		let select = wrapper.find('select');
		let name = select.attr('name');
		let selected = $('<div class="multi-select-selected" name="' + name + '"></div>')
		let input = $('<input class="multi-select-input" name="' + name + '" hidden>');

		// Add hidden selection field and options field
		wrapper.prepend(input);
		wrapper.append(selected);

		let options = $('<div class="multi-select-options" name="' + name + '"></div>');

		select.find('option').each(function() {

			let selected = $(this).is(':selected');
			let checkbox_choice = $('<div name="' + name + '"><label><input type="checkbox" name="' + name + ":" + $(this).val() + '"' + (selected?' checked="checked"':'') + '> ' + $(this).text() + '</label></div>');
			
			checkbox_choice.find('input').on('change', function() {

				let checked_names = [];

				// Remove all present labels
				let labels = '.multi-select-selected[name=' + name + ']';
				$(labels).empty();

				// Add labels for all  selected checkmarks
				let checked = wrapper.find('input:checked').map(function() {

					let checked_name = $(this).attr('name');
					let checked_name_clean = checked_name.split(':')[1];
					let checked = "<span class='property-badge' name='" + checked_name + "'>" + checked_name_clean + "<i class='fa fa-fw fa-times'></span>";

					checked_names.push(checked_name_clean);
					$(labels).append(checked);
					
					return checked;

				}).get();

				input.val(checked_names.join(","));

			});
			options.append(checkbox_choice);
		});

		wrapper.prepend(options)
		select.remove();
	});
}

/**
 * Convert input string to Unix timestamp
 *
 * @param str  Input string, yyyy-mm-dd ideally
 * @returns {*}  Unix timestamp
 */
 function stringToTimestamp(str) {
	// Converts a text input to a unix timestamp.
	// Only used in Safari (other browsers use native HTML date picker)
	let date_regex = /^\d{4}-\d{2}-\d{2}$/;
	let timestamp;
	if (str.match(date_regex)) {
		timestamp = (new Date(str).getTime() / 1000)
	} else {
		str = str.replace(/\//g, '-');
		str = str.replace(/\s/g, '-');
		let date_objects = str.split('-');
		let year = date_objects[2];
		let month = date_objects[1];
		// Support for textual months
		let testdate = Date.parse(month + "1, 2012");
		if (!isNaN(testdate)) {
			month = new Date(testdate).getMonth() + 1;
		}
		let day = date_objects[0];
		timestamp = (new Date(year, (month - 1), day).getTime() / 1000);
	}
	return timestamp;
}

/**
 * Get absolute API URL to call
 *
 * Determines proper URL to call
 *
 * @param endpoint Relative URL to call (/api/endpoint)
 * @returns  Absolute URL
 */
 function getRelativeURL(endpoint) {
	let root = $("body").attr("data-url-root");
	if(!root) {
		root = '/';
	}
	return root + endpoint;
 }