# Processors

Processors are modules for 4CAT that take a dataset as their input and 
produce another dataset as their output.

They are self-contained Python files using a common API. Refer to the 
source code (`backend/abstract/processor.py`) and the 
[Wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-processor)
for more information on how to make a processor.
Also see our [list of processors on the Wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/Available-processors) for an overview.

All python files contained in this folder can be used as processors via the
4CAT web interface, provided they implement the proper methods and API. The
folder substructure within this folder is for convenience only: it can be used
to organise processor files but has no bearing on how they are displayed in the
web interface or elsewhere.


## Style guide for processor descriptions and status updates
Processor descriptions and status update should use direct and informative language that 
give the user a sense of what 4CAT is doing under the hood as well as any caveats with 
processor steps.

### Descriptions (`description` attribute)

**Shape:** Aim for no more than five short sentences, in this order:
1. **What it does** — start with an imperative verb (`Use…`, `Calculate…`, `Extract…`, `Convert…`).
2. [optional] **What it's for / produces** — the use case or output.
3. [optional] **Notable specifics** — supported options, formats, or providers, made concrete.

**Rules:**
- Use sentence case, as full sentences and with Oxford commas, each ending with a period. 
- Lead with the verb; describe the processor, not the user ("Calculate metrics", not "This processor lets you calculate metrics").
- Be concrete: name the actual metrics, formats, or services.
- State meaningful outputs and limits (e.g., "Produces overall and per-label metrics. Also supports multi-label values.").
- Keep it factual and neutral — no hyperbole ("powerful", "easily", "simply").

### Status updates (`update_status(...)`)

**Shape:** a short phrase naming the **current action**, present-continuous, ending with a period.
- ✅ `"Reading source file."`, `"Downloading thumbnails"`, `"Compressing results into archive"`
- ❌ `"Reading values..."` (no `...`), `"Dataset saved."` (no period), `"Please wait"` (not an action)

**Rules:**
- **Progress phrases** describe what's happening *now*: `<Verb>ing <object>`.
- Use sentence case. For one sentence, don't use a trailing period; for multiple sentences, use periods for each. 
- **Include counts** with f-strings for long loops: `f"Processed {i:,}/{total:,} items"` (thousands separators for readability).
- **For heavy processors, include an indication on per-item timing and total time left**: `f"Processed item {i:,}/{total:,} in {MM:SS}, ~{HH:MM:SS} left"` (thousands separators for readability, HH:MM:SS or MM:SS format depending on processor speed).

#### Final status updates
  - Final status updates should be in past-tense and reflect the overall completion action, e.g., `"Dataset saved"`, `"Compressed results into archive"`.
  - **Warning/error messages** are full, self-contained sentences and are passed with `finish_with_warning()`, `finish_with_error()`, and `is_final=True`.
  - Say what the user needs to know on failure or warning: `"API quota exceeded. Saving the results retrieved so far."`
  - Is there is a known workaround, include it: `"API quota exceeded. Saving the results retrieved so far. Try again later or use a different API key."`