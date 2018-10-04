$(document).ready(function() {



	var idlist = []



	jsonfile = jsonfile.substring(1,(jsonfile.length - 1)) //removing " "

	console.log(jsonfile)

	var li_jsonfile = jsonfile

	li_jsonfile = JSON.parse(li_jsonfile)



	console.log(li_jsonfile)



	str_table = ''

	table_tr = ''



	counter = 0

	hrneeded = true



	activeid = ''



	var audio = new Audio("{{url_for('static',filename='xfilestheme.mp3')}}");

	var playaudio = false



	function createSubmissions(){

		console.log('createSubmissions called')

			for (var i = 0; i < li_jsonfile.length; i++) {			//loop through all submissions

				if ((idlist.includes(li_jsonfile[i]['entry']['id'])) == false){

					console.log('entry not registered yet')

					activeid = li_jsonfile[i]["entry"]['id']

					$('.submissions').append('<div class="submission ' + li_jsonfile[i]['entry']['theme'] + ' ' + li_jsonfile[i]['entry']['meme'] +'" id="' + li_jsonfile[i]['entry']['id'] + '"><span class="btn_expand"> + </span></div>')

					$('.submission#' + activeid).append('<span class="span_theme">' + li_jsonfile[i]['entry']['theme'] + '</span>')

					$('.submission#' + activeid).append('<span class="span_meme">' + li_jsonfile[i]['entry']['meme'] + '</span>')

					$('.submission#' + activeid).append('<span class="span_posttitle">' + li_jsonfile[i]['entry']['title'] + '</span>')

					$('.submission#' + activeid).append('<span class="span_username"> by ' + li_jsonfile[i]['entry']['username'] + '</span>')

					$('.submission#' + activeid).append('<div class="fullpost"></div>')



					idlist.push(li_jsonfile[i]['entry']['id'])



					obj_submission = li_jsonfile[i]['entry']

					console.log('Entry:')

					obj_tables = obj_submission['tables']



					console.log(obj_tables)

					if(obj_tables !== undefined){

						for(var table in obj_tables){						//loop through all objects containing table data

							if (obj_tables.hasOwnProperty(table)) {

								//console.log(table)

								loop_table = obj_tables[table]



								for (var entry in loop_table){

									if (loop_table.hasOwnProperty(entry)) {

										//console.log(loop_table[entry])

										loop_entry = loop_table[entry]



										table_tr = ''



										if(hrneeded){									//create table header based on object keys

											array_tableheaders = Object.keys(loop_entry)

											array_tableheaders.pop()

											//console.log(array_tableheaders)

											for(hr in array_tableheaders){

												table_tr = table_tr + '<th>' + array_tableheaders[hr] + '</th>'

											}

											hrneeded = false

											//console.log(table_tr)

										}



										table_row = ''

										for(var key in array_tableheaders){			//loop through the object entries

											if(key == 0){

												table_row = '<tr>'

											}

											table_row = table_row + '<td>' + loop_entry[array_tableheaders[key]] + '</td>'

										}

										table_row = table_row + '</tr>'

										//console.log('row:')

										//console.log(table_row)

										str_table = str_table + table_row

										table_row = ''

									}

								}

								table_tr = '<table class="table"><tr>' + table_tr + '</tr>' 

								//console.log(table_tr)

								str_table = table_tr + str_table + '</table>'

								//console.log(str_table)

								$('.submission#' + activeid + '> div.fullpost').append(str_table)

								str_table = ''

								table_tr = ''

							}

							hrneeded = true

						}

					}



					obj_images = obj_submission['images']

					console.log(obj_images)

					

					for(var image in obj_images){

						if (obj_images.hasOwnProperty(image)) {

							var linkimg = obj_images[image]['imagelink'].replace(/@/g,'\/')

							$('.submission#' + activeid + '> div.fullpost').append('<img src="' + linkimg + '">')

							$('.submission#' + activeid + '> div.fullpost').append('<p><strong>Comment:</strong> ' + obj_images[image]['comment'] + '</p>')

							$('.submission#' + activeid + '> div.fullpost').append('<p><strong>Score:</strong> ' + obj_images[image]['threadnumber'] + '</p>')

						}

					}



					$('.submission#' + activeid + '> div.fullpost').prepend('<div class="div_notes"><p>' + li_jsonfile[i]['entry']['notes'] + '</p></div>')

					console.log(li_jsonfile[i]['entry']['notes'])



					$('#' + activeid + ' > .fullpost').hide()



					console.log($('#themeselect').val())			//hide the entry if the dropdown isn't selected on that theme

					console.log(li_jsonfile[i]['entry']['theme'])

					if($('#themeselect').val() !== li_jsonfile[i]['entry']['theme'] && $('#themeselect').val() !== 'all'){

						$('.submission#' + activeid).hide()

					}

					if(playaudio){

						audio.play()

						$('.entryindicator').html('New submissions! ')

					}

				}

			}

		}



		createSubmissions()



		playaudio = false



		$(document).keydown(function(e) {

			switch(e.which){

				case 48:

				e.preventDefault();



				playaudio = !playaudio

				console.log(playaudio)

				if(playaudio){

					$('.soundnotification').html('V')



				}

				else{

					$('.soundnotification').html('X')

				}

				break;



				default: return;

			}

		});



		$('.submissions').on('click','.btn_expand', function(){

			showdivID = $(this).parent().prop('id')

			console.log(showdivID)



			console.log($(this).next('.fullpost'))

			$(this).parent().find('.fullpost').toggle()



			$(this).toggleClass("expanded");

			if($(this).hasClass("expanded")) {

				$(this).html(" - ");

			} else {

				$(this).html(" + ");

			}

		});



		$('#themeselect').on('change', function(){

			changeFilters()

		});

		$('#memeselect').on('change', function(){

			changeFilters()

		});



		function changeFilters(){

			themefilter = $('#themeselect').val()

			memefilter = $('#memeselect').val()

			if(themefilter == 'all' && memefilter == 'all'){

				$('.submission').show()

			}

			else if(memefilter == 'all'){

				$('.submission').show()

				$('.submission:not(.' + themefilter + ')').hide()

			}

			else if(themefilter == 'all'){

				$('.submission').show()

				$('.submission:not(.' + memefilter + ')').hide()

			}

			else{

				$('.submission').show()

				$('.submission:not(.' + memefilter + ')').hide()

				$('.submission:not(.' + themefilter + ')').hide()

			}

		}



		$('#btn_adminposts').click(function(){

			$('.submission:not(.presentation)').hide()

			$('.submission.presentation').show()

				//$('.' + themefilter).show()

			});



		$('#btn_submissions').click(function(){

			$('.submission.presentation').hide()

			$('.submission:not(.presentation)').show()

			$("#themeselect").val("all");

			$("#memeselect").val("all");

				//$('.' + themefilter).show()

			});

		



		$('.submission.presentation').hide()



		var removenotification = false

		window.setInterval(function(){					//check for new entries every 5 seconds

			console.log('checking for new entries')

			removenotification = !removenotification

			if(removenotification == false){

				$('.entryindicator').html('')

			}

			$.ajax({

				data: 'request',

				type: 'POST',

				contentType: 'text',

				url: "/update",

				success: function(response){

					console.log('received json');

					

					json_update = response.substring(1,(response.length - 1))

					json_update = JSON.parse(response)

					//console.log(response)

					for(var z = 0; z < json_update.length; z++){

						if (idlist.includes(json_update[z]['entry']['id']) == false){

							//idlist.push(json_update[z]['entry']['id'])

							li_jsonfile = json_update

							console.log('new entry')

							console.log('li_jsonfile')

							//console.log(json_update[i]['entry'])

							createSubmissions()

							console.log(idlist)

							console.log(idlist.length + ' items')

						}

					}

				},

				error: function(error){

					console.log('error');

					console.log(error);

				}

			});

		}, 5000);



$('img').click(function(){

	window.open($(this).attr('src'), '_blank');

});



var obj_adminlinks = {

	"post1": [],

	"post2": [],

	"post3": ["{{url_for('static', filename='presentationimg/internet_history_timeline.png')}}"],

	"post100": [],

	"post5": ["{{url_for('static', filename='presentationimg/vernacularweb_diagram.jpg')}}"],

	"post4": ["{{url_for('static', filename='presentationimg/amerimutt_wall.png')}}","{{url_for('static', filename='presentationimg/amerimutt_dogwhistle.png')}}"],

	"post6": ["{{url_for('static', filename='presentationimg/disdainus_maximus_panorama.svg')}}","{{url_for('static', filename='presentationimg/Penisbearcats.png')}}","{{url_for('static', filename='presentationimg/Kermit_de_la_Frog.png')}}","{{url_for('static', filename='presentationimg/DegeneracySucksSoDoYou.png')}}","{{url_for('static', filename='presentationimg/Prussiaball.png')}}","{{url_for('static', filename='presentationimg/TheTraditionalist.png')}}"],

	"post7": ["{{url_for('static', filename='presentationimg/breitbart1.png')}}","{{url_for('static', filename='presentationimg/breitbart2.png')}}","{{url_for('static', filename='presentationimg/breitbart3.png')}}","{{url_for('static', filename='presentationimg/breitbart4.png')}}","{{url_for('static', filename='presentationimg/breitbart5.png')}}","{{url_for('static', filename='presentationimg/breitbart6.png')}}"],

	"post8": ["{{url_for('static', filename='presentationimg/anticlinton1.png')}}","{{url_for('static', filename='presentationimg/anticlinton2.png')}}","{{url_for('static', filename='presentationimg/anticlinton3.png')}}","{{url_for('static', filename='presentationimg/anticlinton4.png')}}"],

	"post9": ["{{url_for('static', filename='presentationimg/youtube1.png')}}","{{url_for('static', filename='presentationimg/youtube2.png')}}","{{url_for('static', filename='presentationimg/youtube3.png')}}","{{url_for('static', filename='presentationimg/youtube4.png')}}","{{url_for('static', filename='presentationimg/youtube5.png')}}","{{url_for('static', filename='presentationimg/youtube6.png')}}","{{url_for('static', filename='presentationimg/youtube7.png')}}","{{url_for('static', filename='presentationimg/youtube8.png')}}"],

	"post10": ["{{url_for('static', filename='presentationimg/redditpano_hillaryforprison.png')}}","{{url_for('static', filename='presentationimg/redditpano_hillaryforprison2.png')}}"],

	"post11": ["{{url_for('static', filename='presentationimg/MemeWar_in_Reddit.png')}}","{{url_for('static', filename='presentationimg/cnnfakenews.gif')}}","{{url_for('static', filename='presentationimg/cnnfakenews_infograph.gif')}}"],

	"post12": ["{{url_for('static', filename='presentationimg/thedonald1.png')}}","{{url_for('static', filename='presentationimg/thedonald2.png')}}","{{url_for('static', filename='presentationimg/thedonald3.png')}}","{{url_for('static', filename='presentationimg/thedonald4.png')}}","{{url_for('static', filename='presentationimg/thedonald_altrightlanguage.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism1.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism2.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism3.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism4.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism5.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism6.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism7.png')}}","{{url_for('static', filename='presentationimg/culturalmarxism8.png')}}"],

	"post13": ["{{url_for('static', filename='presentationimg/subreddits_commenterspace.png')}}"],

	"post14": ["{{url_for('static', filename='presentationimg/pizzagate_timeline.png')}}","{{url_for('static', filename='presentationimg/pizzagate_postcompilation.gif')}}","{{url_for('static', filename='presentationimg/pizzagate_DMpentagram.png')}}"],

	"post15": ["{{url_for('static', filename='presentationimg/amerimutt.png')}}","{{url_for('static', filename='presentationimg/anime.png')}}","{{url_for('static', filename='presentationimg/australianguy.png')}}","{{url_for('static', filename='presentationimg/biggrin.png')}}","{{url_for('static', filename='presentationimg/comics.png')}}","{{url_for('static', filename='presentationimg/feelsguy.png')}}","{{url_for('static', filename='presentationimg/flags.png')}}","{{url_for('static', filename='presentationimg/happymerchant.png')}}","{{url_for('static', filename='presentationimg/harold.png')}}","{{url_for('static', filename='presentationimg/historicalphotos.png')}}","{{url_for('static', filename='presentationimg/maps.png')}}","{{url_for('static', filename='presentationimg/pepe.png')}}","{{url_for('static', filename='presentationimg/picardia.png')}}","{{url_for('static', filename='presentationimg/quotes.png')}}","{{url_for('static', filename='presentationimg/spurdo.png')}}","{{url_for('static', filename='presentationimg/taylorswift.png')}}","{{url_for('static', filename='presentationimg/thinkingemoji.png')}}","{{url_for('static', filename='presentationimg/antiislam.png')}}","{{url_for('static', filename='presentationimg/antileft.png')}}","{{url_for('static', filename='presentationimg/antisemitism.png')}}","{{url_for('static', filename='presentationimg/christian.png')}}","{{url_for('static', filename='presentationimg/conspiracy.png')}}","{{url_for('static', filename='presentationimg/egyptian.png')}}","{{url_for('static', filename='presentationimg/esoteric.png')}}","{{url_for('static', filename='presentationimg/eunationalism.png')}}","{{url_for('static', filename='presentationimg/historical.png')}}","{{url_for('static', filename='presentationimg/lgbtphobe.png')}}","{{url_for('static', filename='presentationimg/misogyny.png')}}","{{url_for('static', filename='presentationimg/multimeme.png')}}","{{url_for('static', filename='presentationimg/nazism.png')}}","{{url_for('static', filename='presentationimg/nordic.png')}}","{{url_for('static', filename='presentationimg/racialism.png')}}","{{url_for('static', filename='presentationimg/trumpism.png')}}","{{url_for('static', filename='presentationimg/vaporwave.png')}}"],

	"post16": ["{{url_for('static', filename='presentationimg/international_chanosphere.jpg')}}","{{url_for('static', filename='presentationimg/world_meme_comparison_white.png')}}","{{url_for('static', filename='presentationimg/indiachan_india.png')}}","{{url_for('static', filename='presentationimg/indiathemes.png')}}","{{url_for('static', filename='presentationimg/futaba_pol.png')}}","{{url_for('static', filename='presentationimg/2ch.png')}}","{{url_for('static', filename='presentationimg/55chan_pol.png')}}","{{url_for('static', filename='presentationimg/fscchan_pol.png')}}","{{url_for('static', filename='presentationimg/hispachan_pol.png')}}","{{url_for('static', filename='presentationimg/komica_pol.png')}}","{{url_for('static', filename='presentationimg/tahta_b.png')}}"]

}



$('.submission.presentation').on('click','.btn_expand', function(){

	console.log(this)

	entryid = $(this).parent().prop('id')

	console.log(entryid)

	var fullpostdiv = $(this).parent().find('.fullpost')

	console.log(fullpostdiv)

	$(fullpostdiv).find('img').each(function(index){

		$(this).attr('display','visible')

		console.log(obj_adminlinks[entryid])

		$(this).attr('src',obj_adminlinks[entryid][index])

	});

});

});

