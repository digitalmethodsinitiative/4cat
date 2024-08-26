$(document).ready(function(){

$(init);

/*
 * Page init
 */

// Timer variable to start/reset saving annotations.
var save_timer = null;

function init() {

	// Functional stuff
	page_functions.init();

	// Annotations
	annotations.init();

}

/*
 * Handle annotations
 */
const annotations = {


	init: function() {

		let editor = $("#annotation-fields-editor");
		let editor_controls = $("#annotation-fields-editor-controls");

		// Add a new annotation field when clicking the plus icon
		$("#new-annotation-field").on("click", function(){
			annotations.addAnnotationField();
		});

		// Show and hide the annotations editor
		let toggle_fields = $("#toggle-annotation-fields")
		toggle_fields.on("click", function(){
			if (toggle_fields.hasClass("shown")) {
				$("#toggle-annotation-fields").html("<i class='fas fa-edit'></i> Edit fields");
				toggle_fields.removeClass("shown");
				editor.animate({"height": 0}, 250);
			}
			else {
				$("#toggle-annotation-fields").html("<i class='fas fa-eye-slash'></i> Hide editor");
				toggle_fields.addClass("shown");
				// Bit convoluted, but necessary to restore auto height
				let current_height = editor.height();
				let auto_height = editor.css("height", "auto").height();
				editor.height(current_height).animate({"height": auto_height}, 250, function(){
					editor.height("auto");
				});
			}
		});

		// Show and hide annotations
		$("#toggle-annotations").on("click", function(){
			if ($(this).hasClass("shown")) {
				annotations.hideAnnotations();
			}
			else {
				annotations.showAnnotations();
			}
		});

		// Delete an entire annotation input
		// We're in a grid of threes, so this involves three divs
		editor_controls.on("click", ".annotation-field > .delete-input", function(){
			let parent_div = $(this).parent();
			parent_div.remove();
		});

		// Make saving available when annotation fields are changed
		editor_controls.on("click", ".delete-option-field", function() {
			annotations.deleteOption(this);
		});
		editor_controls.on("change", ".annotation-field-type", function(e) {annotations.toggleField(e.target);});
		
		// Make enter apply the option fields
		editor_controls.on("keypress", "input", function(e){
			if (e.which === 13) {
				annotations.applyAnnotationFields();
			}
		});

		// Save the annotation fields to the database
		$("#apply-annotation-fields").on("click", annotations.applyAnnotationFields);

		// Dynamically add a new option field when another is edited
		editor_controls.on("keyup", ".option-field > input", function(e) {
			if ($(this).val().length > 0) {
				annotations.addOptions(e.target);
			}
		});

		// Keep track of whether the annotations are edited or not.
		let post_annotations = $(".post-annotations");
		post_annotations.on("keydown click change",
							".post-annotation-input, input[type=checkbox], label, option",
							function(){

			let parent = $(this).parent();
			// Navigate one level up if it's a checkbox or dropdown input
			if (parent.hasClass("post-annotation-options")) {
				parent = parent.parent();
			}
			annotations.markChanges(parent);
			annotations.startSaveTimer();
		});

		// Save the annotations to the database
		$("#save-annotations").on("click", function(){
			clearTimeout(save_timer);
			save_timer = null;
			annotations.saveAnnotations();
		});

		// Check whether there's already fields saved for this dataset
		annotations.fieldsExist();

	},

	toggleField: function (el) {
		// Change the type of input fields when switching in the dropdown
		let type = $(el).val();
		let options = $(el).parent().parent().find(".option-fields");
		if (type === "text" || type === "textarea") {
			options.remove();
		}
		else if (type === "dropdown" || type === "checkbox") {
			if (options.children().length === 0) {
				options.append(annotations.getInputField);
			}
		}
	},

	addOptions: function (el){
		// Dynamically a new options for dropdowns and checkboxes in the fields editor.
		// If text is added to a field, and there are 
		// no empty fields available, add a new one.
		let no_empty_fields = true;
		let input_fields = $(el).parent().siblings();

		if (!$(el).val().length > 0) {
				no_empty_fields = false;
			}
		input_fields.each(function(){
			let input_field = $(this).find("input");
			let val = input_field.val();

			if (!val.length > 0) {
				no_empty_fields = false;
			}
		});
		// Add a new field if there's no empty ones
		if (no_empty_fields) {
			$(el).parent().after(annotations.getInputField);
		}

		// Make sure that you can't delete the last remaining field.
		input_fields = $(el).parent().parent();
		$(input_fields).find(".delete-option-field").remove();

		if (input_fields.length > 0) {

			let amount = $(input_fields).find(".option-field").length;
			let count = 0;

			$(input_fields).find(".option-field").each(function(){
				count++;

				// Don't add a delete option for the last (empty) input.
				if (count === amount) {
					return false;
				}
				$(this).append(`
					<a class="button-like-small delete-option-field"><i class='fas fa-trash'></i></a>`);
			});
		}
	},

	deleteOption: function (el) {
		let input_fields = $(el).parent().parent();
		$(el).parent().remove();

		// Make sure you can't delete the last element
		if (input_fields.find(".option-field").length === 1) {
			input_fields.find(".delete-option-field").remove();
		}
	},

	parseAnnotationFields: function () {
		/*
		Validates and converts the fields in the annotations editor.
		Returns an object with the set annotation fields.
		*/

		let annotation_fields = {};
		let warning = "";
		let labels_added = []

		annotations.warnEditor("");

		$(".annotation-field-label").removeClass("invalid")

		// Parse information from the annotations editor.
		$(".annotation-field").each(function(){

			let ann_field = $(this);

			let label_field = ann_field.find(".annotation-field-label");
			let type = ann_field.find(".annotation-field-type").val();
			let option_fields = ann_field.find(".option-fields");
			let label = label_field.val().replace(/\s+/g, ' ');
			let no_options_added = false

			// Get the ID of the field, so we
			// can later check if it already exists.
			let field_id = ann_field.attr("id").split("-")[1];

			// Make sure the inputs have a label
			if (!label.length > 0) {
				label_field.addClass("invalid");
				warning  = "Field labels can't be empty";
			}
			// Make sure the labels can't be duplicates
			else if (labels_added.includes(label)) {
				warning = "Field labels must be unique";
				label_field.addClass("invalid");
			}

			// We can't add field labels that are also existing column names
			else if (original_columns.includes(label)) {
				warning = "Field label " + label + " is already present as a dataset item, please rename.";
				label_field.addClass("invalid");
			}

			// Keep track of the labels we've added
			labels_added.push(label);
			if (type === "text" || type === "textarea") {
				annotation_fields[field_id] = {"type": type, "label": label};
			}
			// Add options for dropdowns and checkboxes
			else if (option_fields.length > 0) {
				let options = new Map(); // Map, because it needs to be ordered
				let option_labels = [];

				no_options_added = true;

				option_fields.find(".option-field").each(function(){
					let option_input = $(this).find("input");
					let option_label = option_input.val();
					let option_id = option_input.attr("id").replace("option-", "");

					// New option label
					if (!option_labels.includes(option_label) && option_label.length > 0) {
						// We're using a unique key for options as well.
						options.set(option_id, option_label);
						option_labels.push(option_label);
						no_options_added = false;
					}
					// Input fields must have a unique label.
					else if (option_labels.includes(option_label)) {
						warning = "Fields must be unique";
						$(this).addClass("invalid");
					}
					// Fields for dropdowns and checkboxes may be emtpy.
					// We simply don't push them in that case.
					// But there must be at least one field in there.

				});
				if (no_options_added) {
					warning = "At least one field must be added";
					ann_field.find(".option-fields .option-field input").first().addClass("invalid");
				}

				if (options.size > 0) {
					// Strip whitespace from the input field key
					label = label.replace(/\s+/g, ' ');
					annotation_fields[field_id] = {"type": type, "label": label, "options": Object.fromEntries(options)};
				}
			}
		});

		if (warning.length > 0) {
			return warning;
		}
		return annotation_fields;
	},

	parseAnnotation: function(el) {
		/*
		Converts the DOM objects of an annotation
		to an annotation object.

		Must be given a .post-annotation div element.
		*/

		let ann_input = el.find(".post-annotation-input");
		let ann_classes = el.attr("class").split(" ");
		let ann_type = ann_classes[2].replace("type-", "");
		let field_id = ann_classes[1].replace("field-", "");
		let item_id = ann_classes[3].replace("item-id-", "");
		let label = el.find(".annotation-label").text();
		let author = el.find(".annotation-author").html();
		let options = el.find(".annotation-options").html();
		let timestamp = parseInt(el.find(".epoch-timestamp-edited").html());

		let val = undefined;

		// If there are values inserted or things changed, return an annotation object.
		// even if the value is an empty string.

		if (ann_type === "text" || ann_type === "textarea") {
			val = ann_input.val();
		} else if (ann_type === "dropdown") {
			val = $(ann_input).find(":selected").val();
		} else if (ann_type === "checkbox") {
			val = [];
			el.find(".post-annotation-input").each(function () {
				let checkbox = $(this);
				if (checkbox.prop("checked") === true) {
					val.push(checkbox.val());
				}
			});
		}

		// Create an annotation object and add them to the array.
		let annotation = {
			"field_id": field_id,
			"item_id": item_id,
			"label": label,
			"type": ann_type,
			"value": val,
			"author": author,
			"by_processor": false, // Explorer annotations are human-made!
			"timestamp": timestamp,
			"options": options,
		}
		return annotation;
	},

	applyAnnotationFields: function (e){
		// Applies the annotation fields to each post on this page.

		// First we collect the annotation information from the editor

		let new_annotation_fields = annotations.parseAnnotationFields(e);

		// Show an error message if the annotation fields were not valid.
		if (typeof new_annotation_fields == "string") {
			annotations.warnEditor(new_annotation_fields);
		}

		// If everything is ok, we're going to add
		// the annotation fields to each post on the page.
		else {

			$("#apply-annotation-fields").html("<i class='fas fa-circle-notch spinner'></i> Applying")
			
			// Remove warnings
			annotations.warnEditor("")
			$("#annotation-field").find("input").each(function(){
				$(this).removeClass("invalid");
			});
			$(".option-fields").find("input").each(function(){
				$(this).removeClass("invalid");
			});

			// We store the annotation fields in the dataset table.
			// First check if existing annotations are affected.
			if (annotation_fields) {
				annotations.checkFieldChanges(new_annotation_fields, annotation_fields);
			}
			else {
				annotations.saveAnnotationFields(new_annotation_fields);
			}
		}
	},

	saveAnnotationFields: function (new_fields){
		// Save the annotation fields used for this dataset
		// to the datasets table.
		// `old fields` can be given to warn the user if changes to existing fields
		// will affect annotations, like deleting a field or changing its type.

		let dataset_key = $("#dataset-key").text();

		if (new_fields.length < 1) {
			return;
		}

		// AJAX the annotation forms
		$.ajax({
			url: getRelativeURL("explorer/save_annotation_fields/" + dataset_key),
			type: "POST",
			contentType: "application/json",
			data: JSON.stringify(new_fields),
			success: function () {
				// If the query is accepted by the server
				// simply reload the page to render the template again
				window.location.replace(window.location.href);
			},
			error: function (error) {
				console.log(error);

				if (error.status == 400) {
					annotations.warnEditor(error.responseJSON.error);
				}
				else {
					annotations.warnEditor("Server error, couldn't save annotation fields.")
				}
				$("#apply-annotation-fields").html("<i class='fa-solid fa-check'></i> Apply");
			}
		});
	},

	checkFieldChanges(new_fields, old_fields) {

		let deleted_fields = [];
		let changed_type_fields = [];

		// Warn the user in case fields are deleted or changed from text to choice.
		if (old_fields) {
			let text_fields = ["text", "textarea"];
			let choice_fields = ["checkbox", "dropdown"];

			for (let old_field_id in old_fields) {

				// Deleted
				if (!(old_field_id in new_fields) || !new_fields) {
					deleted_fields.push(old_fields[old_field_id]["label"]);
				} else {
					let old_type = old_fields[old_field_id]["type"];
					let new_type = new_fields[old_field_id]["type"]
					if (old_type !== new_type) {
						// Changed from text to choice, or the reverse.
						// In this case annotations will be deleted.
						// Changes from dropdown to checkbox also result in deleted annotations.
						if ((text_fields.includes(old_type) && choice_fields.includes(new_type)) ||
							(choice_fields.includes(old_type) && text_fields.includes(new_type)) ||
							(choice_fields.includes(old_type) && choice_fields.includes(new_type))) {
							changed_type_fields.push(new_type);
						}
					}
				}
			}
		}

		// Ask 4 confirmation
		if (deleted_fields.length > 0 || changed_type_fields.length > 0) {
			let msg = "";
			if (deleted_fields.length > 0 && changed_type_fields.length > 0) {
				msg = `Deleting fields and changing field types will also delete existing annotations that belonged to them.
						Do you want to continue?`;
			}
			else if (changed_type_fields.length > 0) {
				msg = `Changing field types will also delete existing annotations that belonged to them.
						Do you want to continue?`;
			}
			else if (deleted_fields.length > 0) {
				msg = `Deleting fields will also delete existing annotations that belonged to them. 
						Do you want to continue?`;
			}
			popup.confirm(msg, "Confirm", () => {
				annotations.saveAnnotationFields(new_fields);
			});
		}
		else {
			annotations.saveAnnotationFields(new_fields);
		}
	},

	saveAnnotations: function (){
		// Write the annotations to the dataset and annotations table.

		// First we're going to collect the data for this page.
		// Loop through each post's annotation fields.
		let anns = [];
		let dataset_key = $("#dataset-key").text();

		$(".posts > li").each(function(){

			let post_annotations = $(this).find(".post-annotations");

			if (post_annotations.length > 0) {

				post_annotations.find(".post-annotation").each(function(){
					
					// Extract annotation object from edited elements
					if ($(this).hasClass("edited")) {
						let annotation = annotations.parseAnnotation($(this));
						if (Object.keys(annotation).length > 0 ) {
							anns.push(annotation);
						}
					}
				});
			}
		})

		let save_annotations = $("#save-annotations");
		save_annotations.html("<i class='fas fa-circle-notch spinner'></i> Saving annotations")

		$.ajax({
			url: getRelativeURL("explorer/save_annotations/" + dataset_key),
			type: "POST",
			contentType: "application/json",
			data: JSON.stringify(anns),

			success: function (response) {
				save_annotations.html("<i class='fas fa-save'></i> Save annotations");
				annotations.notifySaved();
			},
			error: function (error) {
				console.log(error)
				if (error.status == 400) {
					annotations.warnEditor(error.responseJSON.error);
				}
				else {
					annotations.warnEditor("Server error, couldn't save annotations.")
				}
				save_annotations.html("<i class='fas fa-save'></i> Save annotations");
			}
		});
	},

	fieldsExist: function(){
		// Annotation fields are sent by the server
		// and saved in a script in the header.
		// So we just need to check whether they're there.
		return Object.keys(annotation_fields).length >= 1;
	},

	// Save annotations after x seconds if changes have been made
	startSaveTimer: function() {
		// Reset the save timer if it was already ongoing,
		// so we're not making unnecessary calls when edits are still being made.
		if (save_timer){
			clearTimeout(save_timer);
			save_timer = null;
		}
		save_timer = setTimeout(function() {
			annotations.saveAnnotations();
		}, 3000);
	},

	warnEditor: function(warning) {
		// Warns the annotation field editor if stuff's wrong
		let warn_field = $("#input-warning");
		warn_field.html(warning);
		if (warn_field.hasClass("hidden")) {
			warn_field.removeClass("hidden");
			warn_field.fadeIn(200);
		}
	},

	notifySaved: function() {
		// Flash a fixed div with the notice that annotations are saved.
		let notice = $("#save-annotations-notice");
		if (!notice.is(":visible")) {
			notice.fadeIn(300);
			notice.delay(1500).fadeOut(1000);
		}
	},

	showAnnotations: function() {
		let ta = $("#toggle-annotations");
		ta.addClass("shown");
		ta.html("<i class='fas fa-eye-slash'></i> Hide annotations");
		// Bit convoluted, but necessary to have auto height
		let pa = $(".post-annotations");
		let current_height = pa.height();
		let auto_height = pa.css("height", "auto").height();
		pa.height(current_height).animate({"height": auto_height}, 250, function(){
			pa.height("auto");
		});
	},

	hideAnnotations: function() {
		let ta = $("#toggle-annotations");
		ta.removeClass("shown");
		ta.html("<i class='fas fa-eye'></i> Show annotations");
		let pa = $(".post-annotations");
		pa.animate({"height": 0}, 250);
	},

	addAnnotationField: function(){
		/*
		Adds an annotation field input element;
		these have no IDs yet, we'll add a hashed database-label string when saving.
		*/

		let annotation_field = `
			<li class="annotation-field" id="field-tohashrandomint">
				<i class="fa fa-fw fa-sort handle" aria-hidden="true"></i>
				 <span class="annotation-fields-row">
					<input type="text" class="annotation-field-label" name="annotation-field-label" placeholder="Label">
				</span>
				 <span>
					<select name="annotation-field-type" class="annotation-field-type">
						<option class="annotation-field-option" value="text" selected>Text</option>
						<option class="annotation-field-option" value="textarea">Text (large)</option>
						<option class="annotation-field-option" value="dropdown">Single choice</option>
						<option class="annotation-field-option" value="checkbox">Multiple choice</option>
					</select>
				</span>
				<span class="option-fields"></span>
				<a class="button-like-small delete-input"><i class="fas fa-trash"></i></a>
            </li>
			`.replace("randomint", Math.floor(Math.random() * 100000000).toString());
		$("#annotation-field-settings").append(annotation_field);
	},

	getInputField: function(id){
		// Returns an option field element with a pseudo-random ID, if none is provided.
		if (id === undefined || id === 0) {
			id = Math.floor(Math.random() * 100000000).toString();
		}
		return "<span class='option-field'><input type='text' id='option-" + id + "' placeholder='Option'></span>";
	},

	markChanges: function(el) {
		// Adds info on edits on post annotation to its element, so we can save these to the db later.
		// Currently includes the time of edits and the username of the annotator.
		let current_username = $("#current-username").html();
		let current_date = Date.now() / 1000;
		$(el).addClass("edited");
		$(el).find(".annotation-author").html(current_username);
		$(el).find(".epoch-timestamp-edited").html(current_date);
		$(el).find(".timestamp-edited").html(getLocalTimeStr(current_date));
	}
};

const page_functions = {
	init: function() {
		document.querySelectorAll('.quote a').forEach(link => link.addEventListener('mouseover', function() {
			let post = 'post-' + this.getAttribute('href').split('-').pop();
			document.querySelector('#' + post).classList.add('highlight');
		}));
		document.querySelectorAll('.quote a').forEach(link => link.addEventListener('mouseout', function() {
			document.querySelectorAll('.thread li').forEach(link => link.classList.remove('highlight'));
		}));

		// Change timestamps to the client's timezone
		document.querySelectorAll(".timestamp-to-convert").forEach(function(el){
			el.innerText = getLocalTimeStr(el.innerText);
		});

		// Make annotation field editor sortable with jQuery UI.
		$('#annotation-field-settings').sortable({
            cursor: "s-resize",
            handle: ".handle",
            items: "li",
            axis: "y",
			change: function() {

			}
        });

		// Reorder the dataset when the sort type is changed
		$(".sort-select").on("change", function(){

			// Get the column to sort on, an whether we should sort in reverse.
			let selected = $("#column-sort-select").find("option:selected").val();
			let order = $("#column-sort-order").find("option:selected").val();

			sort_order = ""
			if (order === "reverse"){
				sort_order = "&order=reverse"
			}

			let dataset_key = $("#dataset-key").text();
			window.location.href = getRelativeURL("results/" + dataset_key + "/explorer/?sort=" + selected + sort_order);
		});

		// Change the dropdown sort option based on the URL parameter
		let searchParams = new URLSearchParams(window.location.search)
		let selected = searchParams.get("sort");
		let sort_order = searchParams.get("order");
		$("#column-sort-select").find("option[value='" + selected + "']").attr("selected", "selected");
		if (sort_order) {
			$("#column-sort-order").find("option[value='" + sort_order + "']").attr("selected", "selected");
		}
	}
};

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

function getLocalTimeStr(epoch_timestamp) {
	let local_date = new Date(parseInt(epoch_timestamp) * 1000)
	local_date = Intl.DateTimeFormat("en-GB", {dateStyle: "medium", timeStyle: "medium"}).format(local_date);
	return local_date
}

});