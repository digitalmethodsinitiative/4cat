	function handleFileSelect(e) {			//gets called when the user uploads a file
		files = e.target.files;
		file = files[0];
		readFile(this.files[0]);
	}

	function readFile(file){					//filereader
		var reader = new FileReader();
		reader.readAsText(file);
		reader.onload = function(event){
			loadedfile = event.target.result;
			if(file.name.substring(file.name.length - 3) == "csv"){		//object is already stored in 'csv'
				uploadeddata = $.csv.toObjects(loadedfile);
		}
		else if (file.name.substring(file.name.length - 3) == "tab") {
			uploadeddata = $.tsv.parseObjects(loadedfile);
		}

		var propertynames = Object.getOwnPropertyNames(uploadeddata[0]);			//printing the column headers
		var html = 'Columns: ';											//so the user knows what to input
		for(var item in propertynames){
			html += propertynames[item] + ', ';
		}
		html = html.substring(0, html.length - 2);
		$('.columnsdiv').text(html);

		verifyColumnNames();
	}
	reader.onerror = function(){
		alert('Unable to read ' + file.fileName);
	}
}