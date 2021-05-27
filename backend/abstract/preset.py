"""
Queue a series of processors at once via a preset
"""
import abc
from backend.abstract.processor import BasicProcessor

from common.lib.dataset import DataSet


class ProcessorPreset(BasicProcessor):
	"""
	Processor preset
	"""
	def process(self):
		"""
		This queues a series of post-processors to run in sequence, with an
		overarching dataset to which the results of the last processor in the
		sequence are copied. The processor pipeline is then attached to the
		overarching dataset so it is clear that all processors were run as part
		of that particular preset.
		"""
		pipeline = self.get_processor_pipeline()

		# make sure the last item in the pipeline copies to the preset's dataset
		pipeline = pipeline.copy()
		pipeline[-1]["parameters"]["attach_to"] = self.dataset.key

		# map the linear pipeline to a nested processor parameter set
		while len(pipeline) > 1:
			last = pipeline.pop()
			pipeline[-1]["parameters"]["next"] = [last]

		analysis_pipeline = DataSet(parameters=pipeline[0]["parameters"], type=pipeline[0]["type"], db=self.db,
								 parent=self.dataset.key)

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