$(document).ready(function(){

	// Add the first field
	$("#annotation-fields").append(get_annotation_div());

	// Show and hide the annotations editor
	$("#toggle-annotation-fields").on("click", function(){
		$("#annotations-editor").toggle(100);
	});

	// Add a new annotation field when clicking the plus icon
	$("#add-annotation-field").on("click", function(){
		// Make sure to give it a unique ID.
		$("#annotation-fields").append(get_annotation_div());
	});

	// Save the annotations fields to the database
	$("#save-annotation-fields").on("click", function(){
		apply_annotation_fields();
	});

	// Change the type of input fields when switching in the dropdown
	$("#annotation-fields").on("change", ".annotation-field > .annotation-field-type", function(){
		let type = $(this).val();
		if (type == "text" || type == "textarea") {
			$(this).parent().find(".input-fields").remove();
		}
		else if (type == "dropdown" || type == "checkbox") {
			if (!($(this).siblings(".input-fields").length) > 0) {
				$(this).after("<div class='input-fields'></div>");
				$(this).next().append(get_input_field());
			}
		}
	});

	// Dynamically a new inputs for dropdowns and checkboxes
	$("#annotation-fields").on("change", ".annotation-field > .input-fields > .input-field > input", function(){

		// If text is added to a field, and there are 
		// no empty fields available, add a new one.
		let no_empty_fields = true;
		let input_fields = $(this).parent().siblings();

		input_fields.each(function(){
			var input_field = $(this).find("input");
			let val = input_field.val();

			if (!val.length > 0) {
				no_empty_fields = false;
			}
		});
		if (no_empty_fields) {
			$(this).parent().after(get_input_field());
		}

		// Make sure that you can't delete the last remaining field.
		input_fields = $(this).parent().parent();
		$(input_fields).find(".delete-input-field").remove();

		if (input_fields.length > 0) {

			let amount = $(input_fields).find(".input-field").length;
			let count = 0;

			$(input_fields).find(".input-field").each(function(){
				count++;

				// Don't add a delete option for the last (empty) input.
				if (count == amount) { return false }
				$(this).append("<button class='delete-input-field'><i class='fas fa-trash'></i></button>");
			});
		}
	});

	// Delete an entire annotation input
	$("#annotation-fields").on("click", ".annotation-field > .delete-input", function(){
		$(this).parent().remove();
	});

	// Delete a specific annotation field value
	$("#annotation-fields").on("click", ".annotation-field > .input-fields > .input-field > .delete-input-field", function(){
		
		let input_fields = $(this).parent().parent();
		$(this).parent().remove();

		// Make sure you can't delete the last element
		if (input_fields.find(".input-field").length == 1) {
			input_fields.find(".delete-input-field").remove();
		}
	});

	function apply_annotation_fields(){
		// Collects the annotation information from the editor
		// and adds the right fields to each post on this page.

		let annotation_fields = {};
		let warning = "";

		$("#annotations-input-warning").empty();
		
		// Parse information from the annotations editor.
		$(".annotation-field").each(function(){

			let name_field = $(this).children(".annotation-field-name");
			let name = name_field.val();

			// Get the random identifier of the field, so we
			// can later check if it already exists.
			let num = parseInt(this.id.split("-")[1]);

			// Make sure the inputs have a name
			if (!name.length > 0) {
				name_field.addClass("invalid")
				warning  = "Input names can't be empty. ";
			}
			// Make sure the names can't be duplicates.
			if (name in annotation_fields) {
				warning += "Input names must be unique."
				name_field.addClass("invalid")
			}

			// Set the type of field
			type = $(this).children(".annotation-field-type").val();
			if (type == "text" || type == "textarea") {
				annotation_fields[name] = {"type": type, "num": num};
			}
			// Add input fields for dropdowns and checkboxes
			else {
				inputs = [];
				let no_fields_added = true
				$(this).find(".input-field > input").each(function(){
					
					let input_val = $(this).val();
					let vals = Object.values(inputs)
					let input_id = this.id;

					if (!inputs.includes(input_val) && input_val.length > 0) {
						// We're using a unique key for these to match input fields.
						let input = {};
						no_fields_added = false
						input[input_id] = input_val;
						inputs.push(input);
					}
					// Input fields must have a unique name.
					else if (vals.includes(input_val)) {
						warning = "Dropdown and checkbox fields must be unique.";
						$(this).addClass("invalid");
					}
					// Fields for dropdowns and checkboxes may be emtpy.
					// We simply don't push them in that case.
					// But there must be at least one field in there.
	
				});

				if (no_fields_added) {
					warning = "At least one field must be added.";
					$(this).find(".input-field > input").first().addClass("invalid");
				}

				if (inputs.length > 0) {
					annotation_fields[name] = {"type": type, "num": num};
					annotation_fields[name]["input-fields"] = inputs;
				}
			}
		});

		// If everything is ok, we're going to add
		// the data to each posts on the page.
		if (!warning) {
			
			// We pass this JSON to the server
			json_annotations = JSON.stringify(annotation_fields)

			console.log(annotation_fields);

			// Remove warnings
			$("#annotations-input-warning").empty();
			$("#annotation-fields").find("input").each(function(){
				$(this).removeClass("invalid");
			});
			$(".input-fields").find("input").each(function(){
				$(this).removeClass("invalid");
			});

			// Get the IDs of fields we've already added (could be none)
			let added_fields = []
			$(".posts li").first().find(".post-annotation").each(function(){
				if (!added_fields.includes(this.className.split(" ")[1])){
					added_fields.push(this.className.split(" ")[1]);
				}
			});

			// Add input fields to every posts in the explorer.
			$(".post-annotations").each(function(){

				let post_id = $(this).parent().attr("id");
				//console.log(post_id)

				// Loop through all the annotation fields
				for (field in annotation_fields) {

					// Get some variables
					let input_type = annotation_fields[field]["type"];
					let input_id = "field-" + annotation_fields[field]["num"];
					
					// We first have to check whether this annotation field was already added.
					if (added_fields.includes(input_id)) {

						// Edit the label if is has changed
						label_span = $("#" + input_id + " > .annotation-label")
						label = label_span.first().text();
						if (label != field) {
							label_span.each(function(){
								$(this).text(field);
							});
						}

						// If the type of input field has changed,
						// we'll convert the data where possible.
						let added_input_field = $(this).find("." + input_id + " > .post-annotation-input");
						let old_input_type = added_input_field.first().attr("type");

						// If the change is between a textbox and textarea,
						// simply carry over the text.
						if (input_type != old_input_type) {
							let old_val = added_input_field.val();

							if (input_type == "text" && old_input_type == "textarea") {
								added_input_field.replaceWith($("<input type='text' class='post-annotation-input text-" + field + "'>").val(old_val));
							}
							else if (input_type == "textarea" && old_input_type == "text") {
								added_input_field.replaceWith("<textarea class='post-annotation-input text-" + field + "' type='textarea'>" + old_val + "</textarea>");
							}

							// We don't don't convert for changes between checkboxes and dropdowns
							// or between a text input and dropdowns or checkboxes.

						}

						// For dropdowns and checkboxes, change, add or remove values if they are edited
						if (input_type == "checkbox" || input_type == "dropdown"){
							let fields = annotation_fields[field]["input-fields"];
							for (n in fields) {
								for (key in fields[n]) {

									let field = $(this).find("#" + key);
									let new_val = fields[n][key];
									let option_list = $(this).find(".post-annotation-input-list")

									// If this field does not exist yet, add it
									if (!field.length > 0) {
										if (input_type == "dropdown") {
											option_list.append("<option class='post-annotation-input' id='" + key + "' value='" + new_val + "'>" + new_val + "</option>");
										}
										else if (input_type == "checkbox") {
											option_list.append("<input type='checkbox' class='post-annotation-input' id='check-" + key + "'><label for='check-" + key + "'>" + new_val + "</label>");
										}
									}
									else if (field.val() != new_val) {
										field.val(new_val)
										field.text(new_val)
										field.next("label").text(new_val)
									}
								}
							}
						}

					}
					
					else {
						// Add a label for the field
						el = "<div class='post-annotation " + input_id + "'><label class='annotation-label' for='" + field + post_id + "'>" + field + "</label>";

						// Add a text input for text fields
						if (input_type == "text") {
							el += "<input type='text' class='post-annotation-input text-" + field + "'>";
						}
						else if (input_type == "textarea") {
							el += "<textarea class='post-annotation-input text-" + field + "' type='textarea'></textarea>";
						}

						// Add a dropdown for dropdown fields
						else if (input_type == "dropdown") {

							el += "<select class='post-annotation-input-list select-" + field + "' id='" + field + post_id + "'>";
							
							// Add an empty option field first
							el += "<option class='post-annotation-input' value='none'></option>";

							let fields = annotation_fields[field]["input-fields"];
							
							for (n in fields) {
								for (key in fields[n]) {
									option_id = key;
									option_val = fields[n][key]
								}
								el += "<option class='post-annotation-input' id='" + option_id + "' value='" + option_val + "'>" + option_val + "</option>";
							}
							el += "</select>";
						}

						// Add checkboxes for checkbox fields
						else if (input_type == "checkbox") {

							el += "<div class='post-annotation-input-list checkboxes-" + field + "'>";
							let fields = annotation_fields[field]["input-fields"];
							
							for (n in fields) {
								for (key in fields[n]) {
									option_id = key;
									option_val = fields[n][key]
								}
								el += "<input type='checkbox' class='post-annotation-input' id='" + option_id + "'><label for='" + option_id + "'>" + option_val + "</label>";
							}
							

							el += "</div>";
						}
						el += "</div>";
						$(this).append(el);
					}

					/*// Remove annotation forms that are deleted
					for (f in added_fields) {
						console.log(added_fields[f])
						if (! .includes(added_fields[f]) {
							
						}
					}*/
				}
			});
		}
		else {
			$("#annotations-input-warning").append(warning);
		}
	}

	function write_annotations(){
		// Write the annotations to the annotations table.
	}

	function write_annotations_to_dataset(){
		// Write the annotations fields to the dataset.
	}

	function get_annotation_div(){
		// Returns an annotation div element with a pseudo-random ID
		return "<div class='annotation-field' id='field-" + random_int() + "'><input type='text' class='annotation-field-name' name='annotation-field-name' placeholder='Field name'><button class='delete-input'><i class='fas fa-trash'></i></button><select name='annotation-field-type' class='annotation-field-type'><option class='annotation-field-option' value='text'>Text</option><option class='annotation-field-option' value='textarea'>Textarea</option><option class='annotation-field-option' value='dropdown'>Dropdown</option><option class='annotation-field-option' value='checkbox'>Checkbox</option></select></div>";
	}
	function get_input_field(){
		// Returns an input field element with a pseudo-random ID
		return "<div class='input-field'><input type='text' id='input-" + random_int() + "' placeholder='Value'></div>";
	}

	function random_int(){
		return Math.floor(Math.random() * 100000000)
	}

	document.querySelectorAll('.quote a').forEach(link => link.addEventListener('mouseover', function(e) {
		let post = 'post-' + this.getAttribute('href').split('-').pop();
		document.querySelector('#' + post).classList.add('highlight');
	}));
	document.querySelectorAll('.quote a').forEach(link => link.addEventListener('mouseout', function(e) {
		document.querySelectorAll('.thread li').forEach(link => link.classList.remove('highlight'));
	}));
});