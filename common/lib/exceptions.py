import traceback

class FourcatException(Exception):
	"""
	Base 4CAT exception class
	"""
	def __init__(self, message="", frame=None):
		"""
		Exception constructor

		Takes an optional extra argument, `frame`, the traceback frame of the
		offending code.

		:param str message:  Exception message
		:param frame:  Traceback frame. If omitted, the frame is extrapolated
		from the context.
		"""
		super().__init__(message)
		if not frame:
			frame = traceback.extract_stack()[-2]

		self.frame = frame

class ConfigException(FourcatException):
	"""
	Raised when there is a problem with the configuration settings.
	"""
	pass

class QueueException(FourcatException):
	"""
	General Queue Exception - only children are to be used
	"""
	pass

class ProcessorException(FourcatException):
	"""
	Raise if processor throws an exception
	"""
	pass


class MapItemException(ProcessorException):
	"""
	Raise if processor throws an exception
	"""
	pass


class DataSetException(FourcatException):
	"""
	Raise if dataset throws an exception
	"""
	pass

class DataSetNotFoundException(DataSetException):
	"""
	Raise if dataset does not exist
	"""
	pass


class JobClaimedException(QueueException):
	"""
	Raise if job is claimed, but is already marked as such
	"""
	pass


class JobAlreadyExistsException(QueueException):
	"""
	Raise if a job is created, but a job with the same type/remote_id combination already exists
	"""
	pass


class JobNotFoundException(QueueException):
	"""
	Raise if trying to instantiate a job with an ID that is not valid
	"""
	pass

class QueryException(FourcatException):
	"""
	Raise if there is an issue with form input while creating a dataset
	"""
	pass

class QueryParametersException(QueryException):
	"""
	Raise if a dataset query has invalid parameters
	"""
	pass

class QueryNeedsExplicitConfirmationException(QueryException):
	"""
	Raise if a dataset query needs confirmation
	"""
	pass

class QueryNeedsFurtherInputException(QueryException):
	"""
	Raise if a dataset requires further user input
	"""
	def __init__(self, config):
		super(QueryNeedsFurtherInputException, self).__init__()
		self.config = config

class WorkerInterruptedException(FourcatException):
	"""
	Raise when killing a worker before it's done with its job
	"""
	pass

class ProcessorInterruptedException(WorkerInterruptedException):
	"""
	Raise when killing a processor before it's done with its job
	"""
	pass

class DatabaseQueryInterruptedException(WorkerInterruptedException):
	"""
	Raise when interrupting a DB query before it has finished
	"""
	pass