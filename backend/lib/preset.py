"""
Queue a series of processors at once via a preset
"""
import abc
from backend.lib.processor import BasicProcessor

from common.lib.dataset import DataSet


class ProcessorPreset(BasicProcessor):
	"""
	Processor preset
	"""	
	def process(self):
		"""
		ALL PRESETS MUST PREPEND 'preset-' TO THEIR TYPE.

		This queues a series of post-processors to run in sequence, with an
		overarching dataset to which the results of the last processor in the
		sequence are copied. The processor pipeline is then attached to the
		overarching dataset so it is clear that all processors were run as part
		of that particular preset.
		"""
		pipeline = self.get_processor_pipeline()

		pipeline = self.format_linear_pipeline(pipeline)

		analysis_pipeline = DataSet(
			parameters=pipeline[0]["parameters"],
			db=self.db,
			type=pipeline[0]["type"],
			owner=self.dataset.creator,
			is_private=self.dataset.is_private,
			parent=self.dataset.key, 
			modules=self.modules)
		
		# give same ownership as parent dataset
		analysis_pipeline.copy_ownership_from(self.dataset)

		# this starts the pipeline
		self.queue.add_job(pipeline[0]["type"], remote_id=analysis_pipeline.key)

	def after_process(self):
		"""
		Run after processing

		In this case, this is run immediately after the underlying analyses
		have been queued. This overrides the default behaviour which finishes
		the DataSet after processing; in this case, it is left 'open' until it
		is finished by the last underlying analysis.
		"""
		self.dataset.update_status("Awaiting completion of underlying analyses...")
		self.job.finish()

	@abc.abstractmethod
	def get_processor_pipeline(self):
		"""
		Preset pipeline definition

		Should return a list of dictionaries, each dictionary having a `type`
		key with the processor type ID and a `parameters` key with the
		processor parameters. The order of the list is the order in which the
		processors are run. Compatibility of processors in the list is not
		checked.

		:return list: Processor pipeline definition
		"""
		pass

	def format_linear_pipeline(self, pipeline):
		"""
		Format a linear pipeline to a nested processor parameter set

		:param list pipeline:  Linear pipeline
		:return list:  Nested pipeline
		"""
		if not pipeline:
			raise ValueError("Pipeline is empty")
		
		# make sure the last item in the pipeline copies to the preset's dataset
		# also make sure there is always a "parameters" key
		pipeline = [{"parameters": {}, **p} for p in pipeline.copy()]

		pipeline[-1]["parameters"]["attach_to"] = self.dataset.key

		# map the linear pipeline to a nested processor parameter set
		while len(pipeline) > 1:
			last = pipeline.pop()
			pipeline[-1]["parameters"]["next"] = [last]
	
		return pipeline
	
class ProcessorAdvancedPreset(ProcessorPreset):
	"""
	Similar to ProcessorPreset, but allows for more advanced processor trees with multiple 
	branches and nested processors.
	"""
	def format_linear_pipeline(self, pipeline):
		"""
		No formatting of pipeline is needed for advanced presets
		:param list pipeline:  Linear pipeline
		:return list:  Nested pipeline
		"""
		return pipeline
	
	def get_processor_pipeline(self):
		"""
		Preset pipeline definition
		Should return a list of dictionaries, each dictionary having a `type`
		key with the processor type ID and a `parameters` key with the
		processor parameters. The order of the list is the order in which the
		processors are run. Compatibility of processors in the list is not
		"""
		advanced_pipeline = self.get_processor_advanced_pipeline(attach_to=self.dataset.key)
		if not advanced_pipeline:
			raise ValueError("Pipeline is empty")
		
		# Ensure one of the processors in the advanced pipeline has the attach_to parameter
		all_processors = []
		def collect_processors(processor):
			if "next" in processor["parameters"]:
				for sub_processor in processor["parameters"]["next"]:
					collect_processors(sub_processor)
			all_processors.append(processor)
		for processor in advanced_pipeline:
			collect_processors(processor)
		
		if not any("attach_to" in processor["parameters"] for processor in all_processors):
			raise ValueError("No processor in the advanced pipeline has the attach_to parameter")

		return advanced_pipeline
	
	@abc.abstractmethod
	def get_processor_advanced_pipeline(self, attach_to):
		"""
		Advanced preset pipeline definition

		Similar to base class `get_processor_pipeline`, but allows for more advanced
		processing. This allows multiple processors to be queued in parallel
		or in a nested structure. (i.e., "next" contains a list of processors
		to run in sequence after the each processor.)
		Format a linear pipeline to a nested processor parameter set

		"attach_to" must be added as a parameter to one of the processors. Failure
		to do so will cause the preset to never finish.
		:param list pipeline:  Linear pipeline
		:return list:  Nested pipeline
		"""
		pass