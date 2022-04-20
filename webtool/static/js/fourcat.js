$(init);

/**
 * Page init
 */
function init() {
	// self-updating containers
	dynamic_container.init();

	// tooltips
	tooltip.init();

	// popups
	popup.init();

	// multichoice form elements
	multichoice.init();

	// general form helpers
	ui_helpers.init();

	// result page-specific information handlers
	result_page.init();

	// dataset querying
	query.init();

	// processors
	processor.init();
}

/**
 * Result page dataset trees navigation handlers
 */
const result_page = {
	/**
	 * Set up navigation of result page dataset trees
	 */
	init: function() {
		// dataset 'collapse'/'expand' buttons in result view
		$(document).on('click', '#expand-datasets', result_page.toggleDatasets);

		//allow opening given analysis path via anchor links
		let navpath = window.location.hash.substr(1);
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
	},


	/**
	 * Toggle the visibility of all datasets in a result tree
	 *
	 * @param e  Triggering event
	 */
	toggleDatasets: function (e) {
		let new_text;
		let expanded_state;

		if ($(this).text().toLowerCase().indexOf('expand') >= 0) {
			new_text = 'Collapse all';
			expanded_state = true;
		} else {
			new_text = 'Expand all';
			expanded_state = false;
		}

		$(this).text(new_text);
		$('.processor-expand > button').each(function () {
			let controls = $('#' + $(this).attr('aria-controls'));
			if (controls.attr('aria-expanded')) {
				controls.attr('aria-expanded', expanded_state);
			}
		});
	}
}

/**
 * Post-processor handling
 */
const processor = {
	/**
	 * Set up processor queueing event listeners
	 */
	init: function() {
		// child of child of child etc interface bits
		$(document).on('click', '.processor-queue-button', processor.queue);

		// dataset deletion
		$(document).on('click', '.delete-link', processor.delete);
	},

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

			// if it's a big dataset, ask if the user is *really* sure
			let parent = $(this).parents('li.child-wrapper');
			if(parent.length === 0) {
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
					if (response.hasOwnProperty("messages") && response.messages.length > 0) {
						popup.alert(response.messages.join("\n\n"));
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
							if($('#child-tree-header').hasClass('collapsed')) {
								$('#child-tree-header').attr('aria-hidden', 'false').removeClass('collapsed');
							}
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
					try {
						response = JSON.parse(response.responseText);
						popup.alert('The analysis could not be queued: ' + response["error"], 'Warning');
					} catch(Exception) {
						popup.alert('The analysis could not be queued: ' + response.responseText, 'Warning');
					}
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
				if($('.child-list.top-level li').length === 0) {
					$('#child-tree-header').attr('aria-hidden', 'true').addClass('collapsed');
				}
				query.enable_form();
			},
			error: function(json) {
				popup.alert('Could not delete dataset: ' + json.status, 'Error');
			}
		});
	}
};

/**
 * Query queueing and updating
 */
const query = {
	dot_ticker: 0,
	poll_interval: null,
	query_key: null,

	/**
	 * Set up query status checkers and event listeners
	 */
	init: function() {
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

		// dataset label edit
		$('.result-page .card h2.editable').each(query.label.init);
		$(document).on('click', '.edit-dataset-label', query.label.handle);
		$(document).on('keydown', '#new-dataset-label', query.label.handle);

		// convert dataset
		$(document).on('change', '#convert-dataset', query.convert_dataset)
	},

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
	start: function (extra_data=null) {
		//check form input
		if (!query.validate()) {
			return;
		}

		// Show loader
		query.check_search_queue();

		let form = $('#query-form');
		let formdata = new FormData(form[0]);

		if(extra_data) {
			for(let key in extra_data) {
				formdata.append(key, extra_data[key]);
			}
		}

		// Cache cacheable values
		let datasource = form.attr('class');
		form.find('.cacheable input').each(function() {
			let item_name = datasource + '.' + $(this).attr('name');
			let s = localStorage.setItem(item_name, $(this).val());
		})

		// Disable form
		$('html,body').scrollTop(200);

		// AJAX the query to the server
		$('#query-status .message').html('Sending dataset parameters');
		$.post({
			url: form.attr('action'),
			data: formdata,
			cache: false,
			contentType: false,
			processData: false,

			success: function (response) {
				// If the query is rejected by the server.
				if (response['status'] === 'error') {
					popup.alert(response['message'], 'Error');
				}

				else if(response['status'] === 'confirm') {
					popup.confirm(response['message'], 'Confirm', function() {
						query.start({'frontend-confirm': true});
					});
				}

				// If the query is accepted by the server.
				else {
					query.disable_form();
					$('#query-status .message').html('Query submitted, waiting for results');
					query.query_key = response['key'];
					query.check(query.query_key);

					$('#query-status').append($('<button class="delete-link" data-key="' + query.query_key + '">Cancel</button>'));

					// poll results every 2000 ms after submitting
					query.poll_interval = setInterval(function () {
						query.check(query.query_key);
					}, 4000);
				}
			},
			error: function (error) {
				query.enable_form();
				popup.alert(error['message'], 'Error');
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
					clearInterval(query.poll_interval);
					let keyword = json.label;

					$('#query-results').append('<li><a href="../results/' + json.key + '">' + keyword + ' (' + json.rows + ' items)</a></li>');
					query.enable_form();
					popup.alert('Query for \'' + keyword + '\' complete!', 'Success');
				} else {
					let dots = '';
					for (let i = 0; i < query.dot_ticker; i += 1) {
						dots += '.';
					}
					$('#query-status .dots').html(dots);

					query.dot_ticker += 1;
					if (query.dot_ticker > 3) {
						query.dot_ticker = 0;
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
			let block_type = container.hasClass('full-block') ? 'full' : 'status';
			$.getJSON({
				url: getRelativeURL('api/check-query/'),
				data: {
					key: $(this).attr('data-key'),
					block: block_type
				},
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

		// Country flag check
		if ($('#check-country-flag').is(':checked') && ($('#body-input').val()).length < 2 && valid) {

			let common_countries = ['US', 'GB', 'CA', 'AU'];
			let country = $('#country_flag').val();

			// Don't allow querying without date ranges for the common countries
			if (common_countries.includes(country)) {
				let min_date = $('#option-daterange-min').val();
				let max_date = $('#option-daterange-max').val();

				// Max three monhts for the common country flags without any body parameters
				if (max_date - min_date > 7889231) {
					valid = false;
					popup.alert('The date selected is more than three months. Select a date range of max. three months and try again. Only the most common country flags on 4chan/pol/ (US, UK, Canada, Australia) have a date restriction.', 'Error');
				}

				else {
					valid = false;
					$('#input-min-time').focus().select();
					popup.alert('The most common country flags on 4chan/pol/ (US, Canada, Australia) have a date restriction when you want to retreive all of their posts. Select a date range of max. three months and try again.', 'Error');
				}
			}
		}

		// Return true if everyting is passed
		return valid;
	},

	/**
	 * Query form for chosen datasource
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

				//update data source type indicator
				$('#datasource-type-label').html(data.type.join(", "));

				// update data overview link
				$('.data-overview-link > a').attr("href", getRelativeURL('data-overview/' + data.datasource))

				query.handle_density();
				query.custom_board_options();

                // Render custom multiple choice fields
                // should also be rendered dynamically if processor options are expanded.
                if ($('.multichoice-wrapper').length || $('.multi-select-wrapper').length) {
                    multichoice.makeMultichoice();
                    multichoice.makeMultiSelect();
                }
			},
			'error': function() {
				$('#datasource-select').parents('form').trigger('reset');
				popup.alert('Invalid datasource selected.', 'Error');
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
		timestamp -= date_obj.getTimezoneOffset() * 60;  //correct for timezone

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
			let dataset_key = $('article.result').attr('data-dataset-key');

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
					popup.alert('Oh no! ' +response.text, 'Error');
				}
			});
		}
	},

	convert_dataset: function(self) {
		let datasource = $(self.target).val();
		let dataset_key = $('article.result').attr('data-dataset-key');
		
		if (datasource.length > 0) {
			$.post({
				dataType: "json",
				url: '/api/convert-dataset/' + dataset_key + '/',
				data: {to_datasource: datasource},
				cache: false,

				success: function (json) {
					location.reload();
				},
				error: function (response) {
					popup.alert('Oh no! ' + response.text, 'Error');
				}
			});
		}
	}
};

/**
 * Tooltip management
 */
const tooltip = {
	/**
	 * Set up tooltip event listeners
	 */
 	init: function() {
		//tooltips
		$(document).on('mousemove', '.tooltip-trigger', tooltip.show);
		$(document).on('mouseout', '.tooltip-trigger', tooltip.hide);
		$(document).on('click', '.tooltip-trigger', tooltip.toggle);
	},

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
		let is_standalone = $(tooltip_container).hasClass('multiple');

		if ($(tooltip_container).is(':hidden')) {
			$(tooltip_container).removeClass('force-width');
			let position = is_standalone ? $(parent).offset() : $(parent).position();
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

			console.log(position);
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
const popup = {
	/**
	 * Set up containers and event listeners for popup
	 */
	is_initialised: false,
	current_callback: null,

	init: function () {
		$('<div id="blur"></div>').appendTo('body');
		$('<div id="popup" role="alertdialog" aria-labelledby="popup-title" aria-describedby="popup-text"><div class="content"></div><button id="popup-close"><i class="fa fa-times" aria-hidden="true"></i> <span class="sr-only">Close popup</span></button></div>').appendTo('body');

		//popups
		$(document).on('click', '.popup-trigger', popup.show);
		$('body').on('click', '#blur, #popup-close, .popup-close', popup.hide);
		$('body').on('click', '.popup-execute-callback', function() { if(popup.current_callback) { popup.current_callback(); } popup.hide(); });
		$(document).on('keyup', popup.handle_key);

		popup.is_initialised = true;
	},

	alert: function(message, title = 'Notice') {
		if(!popup.is_initialised) {
			popup.init();
		}

		$('#popup').removeClass('confirm').removeClass('render').addClass('alert');

		let wrapper = $('<div><h2 id="popup-title">' + title + '</h2><p id="popup-text">' + message + '</p><div class="controls"><button class="popup-close"><i class="fa fa-check" aria-hidden="true"></i> OK</button></div></div>');
		popup.render(wrapper.html(), false, false);
	},

	confirm: function(message, title = 'Confirm', callback = false) {
		if(!popup.is_initialised) {
			popup.init();
		}

		if(callback) {
			popup.current_callback = callback;
		}

		$('#popup').removeClass('alert').removeClass('render').addClass('confirm');
		let wrapper = $('<div><h2 id="popup-title">' + title + '</h2><p id="popup-text">' + message + '</p><div class="controls"><button class="popup-close"><i class="fa fa-times" aria-hidden="true"></i> Cancel</button><button class="popup-execute-callback"><i class="fa fa-check" aria-hidden="true"></i> OK</button></div></div>');
		popup.render(wrapper.html(), false, false);
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

		$('#popup').removeClass('confirm').removeClass('alert').addClass('render');

		//determine target - last aria-controls value starting with 'popup-'
		let targets = $(parent).attr('aria-controls').split(' ');
		let popup_container = '';
		targets.forEach(function(target) {
			if(target.split('-')[0] === 'popup') {
				popup_container = target;
			}
		});
		popup_container = '#' + popup_container;

		if ($(parent).attr('data-load-from')) {
			popup.render('<iframe src="' + $(parent).attr('data-load-from') + '"></iframe>', true);
		} else {
			popup.render($(popup_container).html());
		}
	},

	render: function (content, is_fullsize=false, with_close_button=true) {
		//copy popup contents into container
		$('#popup .content').html(content);
		if(is_fullsize) {
			$('#popup').addClass('fullsize');
		} else {
			$('#popup').removeClass('fullsize');
		}
		$('#blur').attr('aria-expanded', true);
		$('#popup').attr('aria-expanded', true);

		if(with_close_button) {
			$('#popup-close').show();
		} else {
			$('#popup-close').hide();
		}

		$('#popup embed').each(function () {
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
	 },

	/**
	 * Hide popup when escape is pressed
	 *
	 * @param e
	 */
	 handle_key: function(e) {
		 if(e.keyCode === 27 && $('#popup').attr('aria-expanded')) {
			 popup.hide(e);
		 }
	 }
	};

/**
 * Dynamic panels
 */
const dynamic_container = {
	/**
	 * Set up updater interval for dynamic containers
	 */
	init: function() {
		// Update dynamic containers
		setInterval(dynamic_container.refresh, 250);
	},

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

/**
 * Multi-choice form elements
 */
const multichoice = {
	/**
	 * Set up multichoice events via event listeners
	 */
	init: function() {
		// Multichoice inputs need to be loaded dynamically
		$(document).on('click', '.toggle-button', function () {
			if ($(".multichoice-wrapper, .multi-select-wrapper").length > 0) {
				multichoice.makeMultichoice();
				multichoice.makeMultiSelect();
			}
		});

		// Filter multichoice on search
		$(document).on('input', '.multi-select-search > input', multichoice.filterMultiChoice);
		$(document).on('click', '.multi-select-selected > span', multichoice.removeMultiChoiceOption);
	},

	/**
	 * Make multichoice select boxes so
	 */
	makeMultichoice: function() {
		//more user-friendly select multiple
		$('.multichoice-wrapper').each(function () {

			let wrapper = $(this);
			let select = $(this).find('select');
			let name = select.attr('name');
			let input = $('<input type="hidden" name="' + name + '">');

			wrapper.append(input);

			select.find('option').each(function () {
				let selected = $(this).is(':selected');
				let checkbox_choice = $('<label><input type="checkbox" name="' + name + ':' + $(this).attr('value') + '"' + (selected ? ' checked="checked"' : '') + '> ' + $(this).text() + '</label>');
				checkbox_choice.find('input').on('change', function () {
					let checked = wrapper.find('input:checked').map(function () {
						return $(this).attr('name').split(':')[1];
					}).get();
					input.val(checked.join(','));
				});
				wrapper.append(checkbox_choice);
			});
			select.remove();
		});
	},

	/**
	 * Make multiselect select boxes so
	 */
	makeMultiSelect: function() {
		// Multi-select choice menu requires some code.
		$('.multi-select-wrapper').each(function () {
			let wrapper = $(this);

			// do nothing if already expanded
			if (wrapper.find(".multi-select-input").length > 0) {
				return;
			}

			// get the data we need from the original select and remove it
			let select = wrapper.find('select');
			let name = select.attr('name');
			let given_options = {};
			let num_options = 0;
			let given_default = [];
			select.find('option').each((i, option) => {
				num_options += 1;
				option = $(option);
				given_options[option.attr("value")] = option.text();
				if (option.is(":selected")) {
					given_default.push(option.attr("value"));
				}
			});
			select.remove();

			let selected = $('<div class="multi-select-selected ms-selected-' + name + '" />')
			let input = $('<input class="multi-select-input" name="' + name + '" hidden />');
			let options = $('<div class="multi-select-options ms-options-' + name + '"></div>');

			for (let option in given_options) {
				let selected = (option in given_default);
				let checkbox_choice = $('<label><input type="checkbox" name="' + name + ":" + option + '"' + (selected ? ' checked="checked"' : '') + '> ' + given_options[option] + '</label>');

				checkbox_choice.find('input').on('change', function () {
					let checked_names = [];

					// Remove all present labels
					let labels = '.multi-select-selected.ms-selected-' + name;
					$(labels).empty();

					// Add labels for all  selected checkmarks
					wrapper.find('input:checked').each((i, checked) => {
						let checked_name = $(checked).attr('name').split(':')[1];
						$(labels).append('<span class="property-badge"><i class="fa fa-fw fa-times"></i> ' + checked_name + '</span>');
						checked_names.push(checked_name);
					});

					input.val(checked_names.join(","));

				});
				options.append(checkbox_choice);
			}

			// prepend in reverse order to not get issues with tooltip button
			wrapper.prepend(input);
			wrapper.prepend(selected);
			wrapper.prepend(options);

			if (num_options > 3) {
				let search = $('<div class="multi-select-search ms-search-' + name + '"><input name="filter-' + name + '" placeholder="Type to filter"></div>')
				options.append("<div class='no-match'>No matches</div>");
				$(options).find(".no-match").hide();
				wrapper.prepend(search);
			}
		});
	},

	filterMultiChoice: function(e) {
		let wrapper = $(e.target).parent().parent();
		let query = $(e.target).val().toLowerCase();
		let options = wrapper.find('.multi-select-options');
		let no_match = options.find(".no-match")

		no_match.hide();

		let match = false
		options.find('label').each(function (i, label) {
			if (!$(label).text().toLowerCase().includes(query)) {
				// Doing this in an obtuse way to prevent resizing
				$(label).hide();
			} else {
				match = true
				$(label).show();
			}
		});

		if (!match) {
			no_match.show()
		}
	},

	removeMultiChoiceOption: function() {
		let value = $(this).text().replace(/^\s+|\s+$/g, '');
		$(this).parent().parent().find('input[name$=":' + value + '"]').prop("checked", false).trigger('change');
		$(this).remove();
	}
}

/**
 * Misc UI helpers
 */
const ui_helpers = {
	/**
	 * Initialize UI enhancements via event listeners
	 */
	init: function() {
		$(document).on('click', '.toggle-button', ui_helpers.toggleButton);

		//confirm links
		$(document).on('click', '.confirm-first', ui_helpers.confirm);

		//confirm links
		$(document).on('click', '.prompt-first', ui_helpers.confirm_with_prompt);

		//long texts with '...more' link
		$(document).on('click', 'div.expandable a', ui_helpers.expandExpandable);


		// Controls to change which results show up in overview
		$('.view-controls button').hide();
		$('.view-controls input, .view-controls select, .view-controls textarea').on('change', function () {
			$(this).parents('form').trigger('submit');
		});

		// 'more...' expanders
		$('.has-more').each(function() {
			let max_length = parseInt($(this).attr('data-max-length'));
			let full_value = $(this).text();
			if(full_value.length < max_length) {
				return;
			}
			$(this).replaceWith('<div class="expandable">' + full_value.substring(0, max_length) + '<span class="sr-only">' + full_value.substring(max_length) + '</span><a href="#">...more</a></div>');
		});
	},

	/**
	 * Ask for confirmation before doing whatever happens when the event goes through
	 *
	 * @param e  Event that triggers confirmation
	 * @param message  Message to display in confirmation dialog
	 * @returns {boolean}  Confirmed or not
	 */
	confirm: function(e, message=null) {
		let trigger_type = $(this).prop("tagName");

		if(!message) {
			let action = 'do this';

			if ($(this).attr('data-confirm-action')) {
				action = $(this).attr('data-confirm-action');
			}

			message = 'Are you sure you want to ' + action + '? This cannot be undone.';
		}

		if(trigger_type === 'A') {
			// navigate to link, but only after confirmation
			e.preventDefault();
			let url = $(this).attr('href');

			popup.confirm(message, 'Please confirm', () => {
				window.location.href = url;
			})

		} else if(trigger_type === 'BUTTON' || trigger_type === 'INPUT') {
			// submit form, but only after confirmation
			let form = $(this).parents('form');
			if(!form) {
				return true;
			}

			e.preventDefault();
			popup.confirm(message, 'Please confirm', () => {
				form.submit();
			})
		}
	},


	/**
	 * Ask for confirmation before doing whatever happens when the event goes through
	 *
	 * Also ask for some input to send with the confirmation, if given
	 *
	 * @param e  Event that triggers confirmation
	 * @returns {boolean}  Confirmed or not
	 */
	confirm_with_prompt: function(e) {
		let action = 'do this';

		if ($(this).attr('data-confirm-action')) {
			action = $(this).attr('data-confirm-action');
		}

		let method = $(this).attr('data-confirm-method') ? $(this).attr('data-confirm-method') : 'GET';
		let result = prompt('Please confirm that you want to ' + action + '. This cannot be undone.');
		let html = '';
		let url = $(this).attr('href');

		e.preventDefault();
		if (!result) {
			return false;
		} else {
			if($(this).attr('data-confirm-var')) {
				html = '<input type="hidden" name="' + $(this).attr('data-confirm-var') + '" value="' + result + '">';
			}
			$('<form style="display: none;"/>').attr('method', method).attr('action', url).html(html).appendTo('body').submit().remove();
			return false;
		}
	},

	/**
	 * Handle '...more' expandables
	 * @param e  Event that triggers expanding or un-expanding
	 */
	expandExpandable: function (e) {
		e.preventDefault();

		if ($(this).text() === '...more') {
			$(this).text('...less');
			$(this).parent().find('.sr-only').removeClass('sr-only').addClass('expanded');
		} else {
			$(this).text('...more');
			$(this).parent().find('.expanded').addClass('sr-only').removeClass('expanded');
		}
	},

	/**
	 * Handle generic toggle button
	 *
	 * Uses the 'aria-controls' value of the triggering element to know what to make visible or hide
	 *
	 * @param e  Event that triggers toggling
	 * @param force_close  Assume the event is un-toggling something regardless of current state
	 */
	toggleButton: function(e, force_close=false) {
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
	if (!root) {
		root = '/';
	}
	return root + endpoint;
}
