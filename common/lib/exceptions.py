class FourcatException(Exception):
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

class QueryParametersException(FourcatException):
	"""
	Raise if a dataset query has invalid parameters
	"""
	pass

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