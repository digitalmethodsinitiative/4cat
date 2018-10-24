$(function() {



	/*WARNING: DEPRECATED CODE */

	$('#btn_go_old').bind('click', function() {
		btn_filter = $('input[name=filterradio]:checked').val()
		switch(btn_filter) {
			case "substring":
			substringFilter()
			break;
			case "textanalysis":
			wordAnalysis()
			break;
			case "allimgs":
			showAllImages()
			break;
			case "textimgs":
			searchImages()
			break;
			default:
			alert('Select filtering method')
		} 
	});

	// fetching a sample HTML table of the selected csv
	$('#sample_csv').bind('click', function(){
		$('.loader').show()
		console.log('load/' + selectedcsv)
		$.ajax({
			dataType: "text",
			url: 'load/' + selectedcsv,
			success: function(response) {
				console.log('success');
				$('#results').html('<div class="result-' + $('#dataselection option:selected').text() + '-sample">' + response + '</div>')
				$('.loader').hide()
				$('#resultsheadertext').html($('#dataselection').find(":selected").text() + ' data sample')
				$('table.dataframe').addClass("table-responsive")
				$('table.dataframe').removeClass("dataframe")
			},
			error: function(error) {
				console.log('error')
				console.log(error);
				$('#results').html('<h3>' +$('#dataselection option:selected').text() + " error</h3>")
				$('.loader').hide()
			}
		});
	});

	//fetching a HTML table with comments containing a search query
	function substringFilter(){
		$('.loader').show()
		selectedcsv = selectedcsv
		searchquery = $('#searchinput').val()
		bool_histo = 0
		if ($('#check_frequency').is(":checked")){
			bool_histo = 1
		}

		//create legible file label for comment or title (so files won't overwrite)
		commentortitle = $('#select_stringlocation').val()
		if(commentortitle == '0'){ label_commentortitle = 'comment'; }
		else{ label_commentortitle = 'title'; }

		mindate = ''
		maxdate = ''

		if($('#check_time').is(':checked')){
			mindate = $('#input_mintime').val()
			maxdate = $('#input_maxtime').val()
			console.log(mindate, maxdate)
			mindate = Date.parse(mindate);
			maxdate = Date.parse(maxdate);
			mindate = mindate / 1000
			maxdate = maxdate / 1000
			console.log(mindate, maxdate)
			substringurl = 'search/' + selectedcsv + '/' + searchquery + '/' + platformselected + '/' + bool_histo + '/' + commentortitle + '/' + mindate + '/' + maxdate
		}
		else{
			substringurl = 'search/' + selectedcsv + '/' + searchquery + '/' + platformselected + '/' + bool_histo + '/' + commentortitle
		}
		console.log(bool_histo)
		console.log(substringurl)
		$.ajax({
			dataType: "text",
			url: substringurl,
			success: function(response) {
				console.log('success');
				if($(response).find('TD').length > 0){
					$('#results').html('<div class="result-' + $('#dataselection option:selected').text() + searchquery + '-search">' + response + '</div>')
					$('#resultsheadertext').html($('#dataselection').find(":selected").text() + ' search for "' + searchquery + '"')
					$('#imagenavigationdiv').removeClass('active')
					$('#imagenavigationdiv').addClass('inactive')
					//console.log(response)
					$('table.dataframe').addClass("table-responsive")
					$('table.dataframe').removeClass("dataframe")
					$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/substringfilters/mentions_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv">mentions_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv</a></p>')
					// also add trends data and img if checked
					if(bool_histo == 'true'){
						$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/substringfilters/occurrances_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv">occurrances_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv</a></p>')
						$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/frequencygraphs/trends_' + searchquery + '.png">trends_' + searchquery + '.png</a></p>')
						$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/frequencygraphs/trends_' + searchquery + '.svg">trends_' + searchquery + '.svg</a></p>')
					}
				}
				else if(response == 'file_exists'){
					alert('This query has already been processed before. File already exists.\n\nDownload it in the data panel.')
					$('.loader').hide()
					$('#imagenavigationdiv').removeClass('active')
					$('#imagenavigationdiv').addClass('inactive')
					$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/substringfilters/mentions_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv">mentions_' + label_commentortitle + '_' + searchquery + '_' + mindate + '_' + maxdate + '.csv</a></p>')
				}
				else if(response == 'invalid query'){
					alert('Please input a valid query.\n\nValid queries:\n- 3 or more characters\n- Not an English stopword (like "and" or "you")\n\nThe dataset is large, so a broad query will overflow the server.')
				}
				else if(response == 'no_match_on_date'){
					alert('No match on date.\n\nCheck your date input and select a wider range to check more posts.')
				}
				else{
					alert('Substring does not occur in this dataset')
				}

				$('.loader').hide()
				$('#imagenavigationdiv').removeClass('active')
				$('#imagenavigationdiv').addClass('inactive')
			},
			error: function(error) {
				console.log('error');
				$('#results').html("<h3>Error</h3>")
				$('.loader').hide()
			}
		});
	}

	//single word frequencies, bigrams, trigrams
	function wordAnalysis(){
		$('.loader').show()
		selectedcsv = selectedcsv
		filtermethod = $('input[name=wordanalysismethod]:checked').val()
		colocationword = $('input[name="colocationword"]').val()
		colocation_disabled = $('input[name="colocationword"]').is(':disabled')
		console.log(colocationword)
		windowsize = $('#windowsize').val()
		sendajax = true
		if (platformselected == 'chans' && colocation_disabled == false && colocationword.length < 3){
			alert('Enter a colocation word with at least three characters.')
			sendajax = false
		}
		// for word colocations
		else if(colocation_disabled == false && colocationword !== ''){
			wordanalysis_url = 'wordanalysis/' + selectedcsv + '/' + filtermethod + '/' + platformselected + '/' + windowsize + '/' + colocationword 
		}
		else{
			wordanalysis_url = 'wordanalysis/' + selectedcsv + '/' + filtermethod + '/' + platformselected
		}
		if(sendajax){
			console.log(wordanalysis_url)
			$.ajax({
				dataType: "text",
				url: wordanalysis_url,
				success: function(response) {
					if(response == 'invalid query'){
						alert('Please input a valid query.\n\nValid queries:\n- 3 or more characters\n- Not an English stopword (like "and" or "you")\n\nThe dataset is large, so a broad query will overflow the server.')
						$('.loader').hide()
						$('#imagenavigationdiv').removeClass('active')
						$('#imagenavigationdiv').addClass('inactive')
					}
					else if(response == 'file_exists'){
						alert('This query has already been processed before. File already exists.\n\nDownload it in the data panel.')
						$('.loader').hide()
						$('#imagenavigationdiv').removeClass('active')
						$('#imagenavigationdiv').addClass('inactive')
						$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/wordanalysis/' + filtermethod + '_' + colocationword + '_' + selectedcsv + '_' + windowsize + '.csv">' + filtermethod + '_' + colocationword + '_' + selectedcsv + '_' + windowsize + '.csv</a></p>')
					}
					else{
						console.log('success');
						$('#results').html('<div class="result-' + $('#dataselection option:selected').text() + '-words">' + response + '</div>')
						$('.loader').hide()
						$('#resultsheadertext').html($('#dataselection').find(":selected").text() + ' word ' + filtermethod)
						$('#imagenavigationdiv').removeClass('active')
						$('#imagenavigationdiv').addClass('inactive')

						$('#submitform').append('<p><a target="_blank" href="static/data/filters/' + platformselected + '/wordanalysis/' + filtermethod + '_' + colocationword + '_' + selectedcsv + '_' + windowsize + '.csv">' + filtermethod + '_' + colocationword + '_' + selectedcsv + '_' + windowsize + '.csv</a></p>')
					}
				},
				error: function(error) {
					console.log('error')
					console.log(error);
					$('.loader').hide()
					$('#imagenavigationdiv').removeClass('active')
					$('#imagenavigationdiv').addClass('inactive')
				}
			});
		}
		else{
			$('.loader').hide()
			$('#imagenavigationdiv').removeClass('active')
			$('#imagenavigationdiv').addClass('inactive')
		}
	}

	//showing images chronologically
	function showAllImages(){
		$('.loader').show()
		csv_selected = selectedcsv

		console.log('images')

		$.ajax({
			dataType: "text",
			url: 'images/' + csv_selected + '/' + '%/' + platformselected, 
			success: function(response) {
				console.log('success');
				obj_jsonimages = JSON.parse(response)
				imglength = 0;
				images = obj_jsonimages['imageurl']
				imgkeys = Object.keys(images);				
				console.log(imgkeys)
				firstimg = imgkeys[0]
				console.log(firstimg)
				lastimg = imgkeys[imgkeys.length -1]
				console.log(lastimg)
				currentimage = firstimg
				$('#imagenavigationdiv').removeClass('inactive')
				$('#imagenavigationdiv').addClass('active')
				maximg = Object.keys(obj_jsonimages[column_imagelink]).length
				imgcount = 1
				$('#imgnotification').html('1/' + maximg)
				showImage(obj_jsonimages, firstimg)
				$('.loader').hide()
				$('#resultsheadertext').html($('#dataselection').find(":selected").text() + ' images')

			},
			error: function(error) {
				console.log('error')
				console.log(error);
				$('.loader').hide()
			}
		});
	}

	//show images alongside a certain word
	function searchImages(){
		$('.loader').show()
		csv_selected = selectedcsv
		imagesearchquery = $('#input_searchimages').val()
		console.log('images')
		$.ajax({
			dataType: "text",
			url: 'images/' + csv_selected + '/' + imagesearchquery + '/' + platformselected, 
			success: function(response) {
				console.log('success');
				obj_jsonimages = JSON.parse(response)
				currentimage = 1
				console.log(obj_jsonimages)

				imglength = 0;
				images = obj_jsonimages['imageurl']

				imgkeys = Object.keys(images);
				console.log(imgkeys)
				firstimg = imgkeys[0]
				console.log(firstimg)
				lastimg = imgkeys[imgkeys.length -1]
				console.log(lastimg)
				currentimage = firstimg

				$('#imagenavigationdiv').removeClass('inactive')
				$('#imagenavigationdiv').addClass('active')
				showImage(obj_jsonimages, firstimg)
				$('.loader').hide()
				$('#resultsheadertext').html($('#dataselection').find(":selected").text() + ' image search for "' + imagesearchquery  + '"')

				$('html,body').scroll({
					scrollTop: $('#resultsheader').offset().top
				});

				if(obj_jsonimages['imageurl'][firstimg] == undefined){
					alert('no matches')
				}
				else{
					console.log('LENGTH:')
					console.log(lastimg);
					maximg = Object.keys(obj_jsonimages[column_imagelink]).length
					imgcount = 1
					$('#imgnotification').html('1/' + maximg)
					showImage(obj_jsonimages, firstimg)
				}
				$('.loader').hide()
			},
			error: function(error) {
				console.log('error')
				console.log(error);
				$('.loader').hide()
			}
		});
	}

	var lastimg = 0
	var firstimg = 0
	var imgcount = 0
	var maximg = 0
	currentimage = firstimg
	imagelink = ''

	function showImage(inputjson, imageno){

		if(platformselected == 'chans'){
			imglink = ($('#dataselection').find(":selected").val())
			imglink = imglink.substr(0, imglink.indexOf('@')); 
			console.log(imglink)
			imagelink = '../static/data/' + imglink + '/' + inputjson[column_imagelink][imageno]
			imagelink = imagelink.replace('@','\/')
		}
		else{
			imagelink = inputjson[column_imagelink][imageno]
		}

		if($.inArray(inputjson[column_imagelink][imageno], array_trackimgs) !== -1){			//check whether the image is already checked
			checkboxstring = '<input type="checkbox" name="imgsubmit" class="imgsubmit" checked>'
		}
		else{
			checkboxstring = '<input type="checkbox" name="imgsubmit" class="imgsubmit">'
		}

		threadindication = ''
		if(platformselected == 'chans'){
			threadindication = '<h3>Thread #' + inputjson[column_threadnumber][imageno] +  '</h3>'
		}

		imgtime = inputjson[column_createdtime][imageno]
		comment = inputjson[column_comment][imageno]
		if(comment == null){
			comment = '-No text in post-'
		}

		$('#results').html(threadindication +  '<p class="imgtime">' + imgtime + '</p><p class="imgpost">' +  comment + '</p><img src="' + imagelink + '">')
		$('#imagenavigationdiv').append('<div class="imagecheckinput"><label>Submit image' + checkboxstring + '</label></div>')

		$('html, body').animate({
			scrollTop: ($('#resultsheader').offset().top)
		},0);
	}

	$('#btn_nextimg').on('click', function() {
		
		if(currentimage < lastimg){
			currentimage++
			while (obj_jsonimages[column_imagelink][currentimage] == undefined && currentimage < lastimg){
				currentimage++
			}
			imgcount++
			$('#imgnotification').html(imgcount + '/' + maximg)
			showImage(obj_jsonimages, currentimage)
		}
		else{
			alert('last image!')
		}
	});

	$('#btn_previmg').on('click', function() {
		
		if(currentimage > firstimg){
			currentimage--
			while (obj_jsonimages[column_imagelink][currentimage] == undefined && currentimage > firstimg){
				currentimage--
			}
			imgcount--
			$('#imgnotification').html(imgcount + '/' + maximg)
			showImage(obj_jsonimages, currentimage)
		}
		else{
			alert('first image')
		}
	});

	array_trackimgs = []				//keeps track of selected images (redundant but works)
	array_imgs = []
	$('#imagenavigationdiv').on('click', '.imagecheckinput > label > input:checkbox', function(){		//when image checkbox is clicked
		
		if (this.checked) {
			console.log('checked')
			imagedata = {}
			imagedata['imagelink'] = imagelink
			imagedata['comment'] = obj_jsonimages[column_comment][currentimage]
			if(platformselected == 'chans'){
				imagedata['threadnumber'] = obj_jsonimages[column_threadnumber][currentimage]
			}
			else{
				imagedata['threadnumber'] = obj_jsonimages[column_score][currentimage]
			}
			array_trackimgs.push(obj_jsonimages[column_imagelink][currentimage])
			array_imgs.push(imagedata)		//add the respective image to array
			console.log(array_imgs)
			$('#submitreview').html(array_imgs.length + ' images')
		}
		else{
			console.log('unchecked')
			index = array_imgs.indexOf(obj_jsonimages[column_imagelink][currentimage])
			console.log(index)
			array_trackimgs.splice(index,1)
			array_imgs.splice(index,1)										//remove respective image from array
			console.log(array_imgs)
			$('#submitreview').html(array_imgs.length + ' images')
		}
	});

	$('#results').on('click', 'input:checkbox.tablecheckbox', function(){	//when table checkbox is clicked
		if (this.checked) {
			console.log('checked')
			isheader = $(this).parent().prev().prop('tagName')
			tableinputs = $(this).parents('table').find('input')
			console.log(tableinputs)
			if(isheader == 'TH'){
				console.log('first checkbox')
				$(tableinputs).prop('checked', true)
			}
		}
		else {
			console.log('unchecked')
			isheader = $(this).parent().prev().prop('tagName')
			tableinputs = $(this).parents('table').find('input')
			console.log(tableinputs)
			if(isheader == 'TH'){
				console.log('first checkbox')
				$(tableinputs).prop('checked', false)
			}
		}
	});

	$('#submitdata').click(function(){
		if($('#input_title').val() == "" || $('#input_username').val() == "" || $('#input_notes').val() == ""){
			alert("Enter a title, username and notes!")
			return -1;
		}
		console.log('generating JSON')
		jsonobject = generateJSON()
		jsonobject = JSON.stringify(jsonobject);

		console.log('sending:')
		console.log(jsonobject)

		$.ajax({
			data: jsonobject,
			type: 'POST',
			dataType: 'json',
			contentType: 'application/json',
			url: "/send",
			success: function(response){
				console.log('received json: ');
				console.log(response)
				window.location.href = '/submissions';
			},
			error: function(error){
				console.log('error');
				console.log(error);
			}
		});
	});

	function uniqId() {
		return Math.round(new Date().getTime() + (Math.random() * 100));
	}

	function generateJSON(){
		var obj_submitdata = {}	

		console.log($('#input_username').val())
		obj_submitdata["title"] = $('#input_title').val()
		obj_submitdata["theme"] = $('#themeselection').val()
		obj_submitdata["meme"] = $('#memeselection').val()
		obj_submitdata["username"] = $('#input_username').val()
		obj_submitdata["notes"] = $('#input_notes').val()
		obj_submitdata["id"] = uniqId()
		console.log(obj_submitdata)

		if(array_imgs.length > 0){
			console.log('submitted images')
			for (var z =  0; z < array_imgs.length; z++) {
				var link_img = array_imgs[z]["imagelink"]
				array_imgs[z]["imagelink"] = link_img.replace(/\//g,'@')
				if(array_imgs[z]["comment"] == null){
					array_imgs[z]["comment"] = 'No comment'
				}
				console.log(array_imgs[z]["imagelink"])
			};
			obj_submitdata["images"] = array_imgs
		}

		if($('input.tablecheckbox:checked').length > 0){						//if there's tables
			$('table').each(function(index){
				console.log('table found')
				title = ($('#dataselection').find(":selected").val())
				keys = []												//get the table headers in an unconvenient way
				$(this).find('th').each(function(index){
					if($(this).html() !== '<input type=\"checkbox\">'){
						keys.push($(this).html())
					}
				});

				console.log(keys)
				obj_tableoutputs = {}
				obj_tableoutputs[title] = {}
				rows = []

				$(this).find('input:checkbox:checked').each(function(index){
					console.log('checkbox found')
					console.log(title)
					input_rowdata = $(this).parent().parent()		//the row data of checked row
					console.log(input_rowdata)

					output_rowdata = {}
					
					$(input_rowdata).find('td').each(function(index){
						innerhtml = $(this).html()
						if(innerhtml !== '<input type=\"checkbox\">'){
							output_rowdata[keys[index]] = (innerhtml)
						}
					});
					rows.push(output_rowdata)
					obj_tableoutputs[title] = rows
					obj_tableoutputs["name"] = ($('#dataselection').find(":selected").text())
				});
				obj_submitdata["tables"] = obj_tableoutputs
			});
	}
	console.log('sending json: ')
	console.log(obj_submitdata)
	return obj_submitdata
}

platformselected = 'chans'
$('#buttonselections').on('click', 'input.platformselect', function(){
	console.log(this.id)
	$('#dataselection>option').attr('selected', false);
	if(this.id == 'radio_selectchans'){
		var newOptions = {"4plebs database": "4plebs-pol-test-database"}
			/*,
			"4chan-snapshot 31-01-2018 01:19:17": "4chan-snapshot-31-01-2018-01-19-17@4chan-snapshot-31-01-2018-01-19-17",
			"4chan-snapshot 31-01-2018 03:00:00": "4chan-snapshot-31-01-2018-03-00-00@4chan-snapshot-31-01-2018-03-00-00",
			"4chan-snapshot-31-01-2018 06:00:00": "4chan-snapshot-31-01-2018-06-00-00@4chan-snapshot-31-01-2018-06-00-00",
			"4chan-snapshot-31-01-2018 09:00:00": "4chan-snapshot-31-01-2018-09-00-00@4chan-snapshot-31-01-2018-09-00-00",
			"4chan-snapshot-31-01-2018 12:00:00": "4chan-snapshot-31-12-2018-03-00-00@4chan-snapshot-31-01-2018-12-00-00",
			"4chan-snapshot-31-01-2018 15:00:00": "4chan-snapshot-31-15-2018-03-00-00@4chan-snapshot-31-01-2018-15-00-00",
			"4chan-snapshot-31-01-2018 18:00:00": "4chan-snapshot-31-01-2018-18-00-00@4chan-snapshot-31-01-2018-18-00-00"*/
			platformselected = 'chans'
			column_comment = 'comment'
			column_author = 'name'
			column_createdtime = 'now'
			column_imagelink = 'imageurl'
			column_score = ''
			column_threadnumber = 'threadnumber'
			column_country = 'country'
			column_subreddit = ''
			column_id = 'id'
			$('#select_stringlocation').removeClass('invisible')
			$('#filter_allimgs').addClass('invisible')
			$('#filter_textimgs').addClass('invisible')
		}
		else if(this.id == 'radio_selectreddit'){
			var newOptions = {
				"Subreddit posts: Kreiswichs 01-2017/12-2017": "reddit-kreiswichs-01-2017-12-2017@reddit-kreiswichs-01-2017-12-2017",
				"Subreddit posts: me_irl 15-12-2017/31-12-2017": "reddit-me_irl-15-12-2017-31-12-2017@reddit-me_irl-15-12-2017-31-12-2017",
				"Subreddit posts: Polandball 01-2017/12-2017": "reddit-polandball-01-2017-12-2017@reddit-polandball-01-2017-12-2017",
				"Subreddit posts: Surrealmemes 01-2017/12-2017": "reddit-surrealmemes-01-2017-12-2017@reddit-surrealmemes-01-2017-12-2017",
				"Subreddit posts: The_Donald 06-10-2017/20-10-2017": "reddit-The_Donald-06-10-2017-20-10-2017@reddit-The_Donald-06-10-2017-20-10-2017",
				"Subreddit posts: The_Donald 05-2017": "reddit-thedonald-052016@reddit-thedonald-052016",
				"Subreddit posts: The_Donald 12-2017": "reddit-thedonald-122017@reddit-thedonald-122017",
				"Subreddit posts: TrollXChromosomes 01-2017/12-2017": "reddit-TrollXChromosomes-01-2017-12-2017@reddit-TrollXChromosomes-01-2017-12-2017",
				"Subreddit posts: Vaporwave Aesthetics 06-2017/12-2017": "reddit-VaporWaveAesthetics_06-2016-12-2017@reddit-VaporWaveAesthetics_06-2016-12-2017"
			};
			platformselected = 'reddit'
			column_comment = 'title'
			column_author = 'author'
			column_createdtime = 'now'	//still have to make sure I have this column
			column_imagelink = 'imageurl'
			column_score = 'score'
			column_country = ''
			column_subreddit = 'subreddit'
			column_id = 'id'
			column_link = 'permalink'
			$('#select_stringlocation').addClass('invisible')
			$('#filter_allimgs').removeClass('invisible')
			$('#filter_textimgs').removeClass('invisible')
		}

		else if(this.id == 'radio_selectfb'){
			var newOptions = {
				//"FB Page images: Smash Usury": "fb-imagefile-SmashUsury@fb-imagefile-SmashUsury",
				"FB Page images: Breitbart": "fb_imagefile-Breitbart@fb_imagefile-Breitbart",
				"FB Page images: Architectural Revival": "fb-imagefile-Architectural Revival@fb-imagefile-Architectural Revival",
				"FB Page images: Degenacy Sucks - So Do You": "fb-imagefile-Degeneracy Sucks_SoDoYou@fb-imagefile-Degeneracy Sucks_SoDoYou",
				"FB Page images: Disdainus Maximus": "fb-imagefile-Disdainus Maximus@fb-imagefile-Disdainus Maximus",
				"FB Page images: Donald J. Trump": "fb-imagefile-Donald J. Trump@fb-imagefile-Donald J. Trump",
				"FB Page images: Earl of Grey": "fb-imagefile-Earl of Grey@fb-imagefile-Earl of Grey",
				"FB Page images: Edgy Egyptian Memes": "fb-imagefile-Edgy Egyptian Memes@fb-imagefile-Edgy Egyptian Memes",
				"FB Page images: Kermit de la Frog - The Mean Green Meme Machine": "fb-imagefile-Kermit de la Frog - The Mean Green Meme Machine@fb-imagefile-Kermit de la Frog - The Mean Green Meme Machine",
				"FB Page images: Make America Great Again Memes": "fb-imagefile-Make America Great Again Memes@fb-imagefile-Make America Great Again Memes",
				"FB Page images: Penisbearcats": "fb-imagefile-Penisbearcats@fb-imagefile-Penisbearcats",
				"FB Page images: Preserve Our Heritage": "fb-imagefile-Preserve Our Heritage@fb-imagefile-Preserve Our Heritage",
				"FB Page images: Prestigious Prussian Memes": "fb-imagefile-Prestigious Prussian Memes@fb-imagefile-Prestigious Prussian Memes",
				"FB Page images: Prestigious Prussian Memes": "fb-imagefile-Prestigious Prussian Memes@fb-imagefile-Prestigious Prussian Memes",
				"FB Page images: Prussiaball": "fb-imagefile-Prussiaball@fb-imagefile-Prussiaball",
				"FB Page images: Rough Roman Memes": "fb-imagefile-Rough Roman Memes@fb-imagefile-Rough Roman Memes",
				"FB Page images: Smash Cultural Marxism": "fb-imagefile-Smash Cultural Marxism@Smash Cultural Marxism",
				"FB Page images: Straight, white, capitalist": "fb-imagefile-Straight, white, capitalist@fb-imagefile-Straight, white, capitalist",
				"FB Page images: The Traditionalist": "fb-imagefile-The Traditionalist@fb-imagefile-The Traditionalist",
				"FB Page images: This is Europa": "fb-imagefile-This is Europa@fb-imagefile-This is Europa",
				"FB Page images: This is Germany": "fb-imagefile-This is Germany@fb-imagefile-This is Germany",
				"FB Page images: Vaporwave": "fb-imagefile-vaporwave@fb-imagefile-vaporwave"};
				
				platformselected = 'fb'
				column_comment = 'name'
				column_author = ''
				column_createdtime = 'created_time'
				column_imagelink = 'imageurl'
				column_score = 'reactionscount'
				column_country = ''
				column_subreddit = ''
				column_id = 'id'
				$('#select_stringlocation').addClass('invisible')
				$('#filter_allimgs').removeClass('invisible')
				$('#filter_textimgs').removeClass('invisible')
			}

			var $el = $("#dataselection");
			$el.empty(); // remove old options
			$.each(newOptions, function(key,value) {
				$el.append($("<option></option>")
					.attr("value", value).text(key));
			});

			$('#dataselection>option:eq(0)').attr('selected', true);

			selectedcsv = ($('#dataselection').find(":selected").val())
			console.log(selectedcsv)
			console.log(platformselected)

		});

$('#btn_clear').on('click', function(){
	$('#results').html('')
	$('#imagenavigationdiv').removeClass('active')
	$('#imagenavigationdiv').addClass('inactive')
});

$("#input_searchimages").keyup(function(event) {
	if (event.keyCode === 13) {
		$("#btn_searchimages").click();
	}
});

$('#radio_selectfb').click();
selectedcsv = ($('#dataselection').find(":selected").val())

	/*$('input[name="wordanalysismethod"]').bind('click', function(){
		if(this.id == 'trigrams' || this.id == 'bigrams'){
			$('#colocationword').attr('disabled', false)
		}
		else{
			$('#colocationword').attr('disabled', true)
		}
	});*/

	//when the main filter radio is changed
	$('input[name=filterradio]').on('change', function(){
		console.log('changed')
		$('input[type="text"]').attr('disabled', true)
		switch(this.value){
			case "substring":
			$('#searchinput').attr('disabled', false)
			break;
			case "textanalysis":
			$('#colocationword').attr('disabled', false)
			
			break;
			case "allimgs":
				//do nothing (yet)
				break;
				case "textimgs":
				$('#input_searchimages').attr('disabled', false)
				break;
				default:
				alert('Select filtering method')
			}
		});

	//when the wordanalysis is changed
	$('input[name=wordanalysismethod]').on('change', function(){
		selected = $(this).val()
		console.log(selected)
		if( selected == 'bigrams'){
			$('#window_size2').removeClass('invisible')
		}
		if (selected == 'trigrams'){
			console.log($('#windowsize').val())
			if ($('#windowsize').val() == '2'){
				$('#window_size3').click()
				$('#windowsize').val('3')
			}
			$('#window_size2').addClass('invisible')
		}
	});

	//when the 'filter on time' checkbox is checked
	$('#check_time').on('change', function(){
		if(this.checked){
			$('#input_mintime').attr('disabled', false)
			$('#input_maxtime').attr('disabled', false)
		}
		else{
			$('#input_mintime').attr('disabled', true)
			$('#input_maxtime').attr('disabled', true)
		}
	});

	$('#radio_selectchans').click();

});