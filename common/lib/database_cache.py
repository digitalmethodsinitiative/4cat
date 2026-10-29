"""
Cache for data that can always be read from the database again
"""
import threading
import hashlib
import time

from pymemcache.client.base import Client as MemcacheClient
from pymemcache.exceptions import MemcacheError, MemcacheClientError, MemcacheServerError, MemcacheIllegalInputError, \
    MemcacheUnexpectedCloseError
from pymemcache import serde

# Errors that mean memcache cannot be used right now
MEMCACHE_ERRORS = (MemcacheError, OSError, ValueError, SystemError)


class CacheMiss:
    """
    Helper class to distinguish memcache misses from true `None` values
    """
    pass


class DatabaseCache:
    """
    Use memcache to serve data faster than reading it from the database.
    
    4CAT does not depend on it as data can always be read from the database 
    again. When memcache cannot be used, `get()` returns `CacheMiss`
    and the data is read from the database instead; nothing is cached until
    memcache can be used again.

    Changing data in the database should be followed by `delete()` for its
    cached value. If memcache cannot be reached for that, it is considered
    down: it is not used again until it can be reached *and* has been cleared,
    because the old value would otherwise be read again.

    Each thread has its own connection to memcache. Use one cache object for
    all threads of a process, so that they all know when memcache is down.

    Note: There is still a gap on failed writes: if a value is written to the 
    database but memcache cannot be reached but another process (not thread) 
    can reach memcache, it will read the old value from memcache. This should 
    be rare; the cache will be cleared when any thread in the failed process 
    can reach memcache again. There is also a timeout on cached values, so 
    they will be read from the database again after a while.
    """
    # How long to wait for memcache before giving up, in seconds. Without a
    # limit, a memcache server that hangs blocks everything that reads
    # from the cache.
    timeout = 1
    # While memcache is down, how often to try to reach it again, in seconds.
    # Each attempt can take seconds (e.g. looking up the address of a stopped
    # Docker container), and a page can read many values, so do not try for
    # each.
    retry_interval = 10
    # While memcache is down, how often to log that it still is, in seconds.
    # Each process logs this, and a warning may be sent to Slack, so not too
    # often: memcache may also be down because it was configured but never
    # set up.
    reminder_interval = 3600
    # How long a value stays cached, in seconds. If a value could not be
    # removed in one process while other processes can still read it, it
    # would otherwise be read indefinitely.
    expire = 600

    def __init__(self, server, key_prefix, logger=None):
        """
        :param str|None server:  Memcache server address, e.g.
        `localhost:11211`. If `None`, nothing is cached.
        :param bytes key_prefix:  Put in front of all keys, to keep them apart
        from those of other users of the same memcache server. Clearing the
        cache still removes their values too; see `clear()`.
        :param logger:  4CAT logger to report problems with memcache to
        """
        self.server = server
        self.key_prefix = key_prefix
        self.logger = logger

        self._connections = threading.local()

        # whether memcache is down, and what to do about it; only changed
        # while holding the lock.
        self._lock = threading.Lock()
        self._down_since = None
        self._last_failure = 0
        self._next_attempt = 0
        self._reminded_at = 0
        self._logged_at = {}

    def get(self, key):
        """
        Get a cached value

        :param bytes|str key:  Key
        :return:  The cached value, or `CacheMiss` if there is none or memcache
        cannot be used
        """
        key = self._safe_key(key)
        return self._command(lambda client: client.get(key, default=CacheMiss), failed=CacheMiss)

    def set(self, key, value):
        """
        Cache a value

        If memcache cannot be used, the value is simply not cached.

        :param bytes|str key:  Key
        :param value:  Value to cache
        """
        key = self._safe_key(key)
        self._command(lambda client: client.set(key, value, expire=self.expire, noreply=False))

    def delete(self, key):
        """
        Remove a cached value

        If this fails, memcache is considered down, and it is cleared before it
        is used again, so the value is not read again either way.

        :param bytes|str key:  Key
        """
        key = self._safe_key(key)
        self._command(lambda client: client.delete(key, noreply=False), removes=True)

    def clear(self):
        """
        Remove all cached values

        This clears the whole memcache server, not only the keys with this
        cache's prefix, because memcache cannot remove keys by prefix. Other
        users of the same server lose their values too, e.g. the rate limiter
        of 4CAT's web interface, which then starts counting again.
        """
        self._command(lambda client: client.flush_all(noreply=False), removes=True)

    def is_available(self):
        """
        Check if memcache can be used right now

        :return bool:
        """
        return self._command(lambda client: client.version() is not None, failed=False)

    def close(self):
        """
        Close this thread's connection to memcache

        Call when a thread is done, to close its connection right away instead
        of when the thread is cleaned up.
        """
        client = getattr(self._connections, "client", None)
        if client:
            try:
                client.close()
            except Exception:
                pass
            finally:
                try:
                    del self._connections.client
                except AttributeError:
                    pass

    def _safe_key(self, key):
        """
        Make a key that memcache accepts

        Keys are made from setting names, tags and user names, which can
        contain any character. Memcache only accepts keys of up to 250 bytes,
        prefix included, without spaces or control characters, and pymemcache
        only accepts ASCII text. A key that does not fit these rules is
        replaced by a code made from it (a hash), so its value can still be
        cached.

        :param bytes|str key:  Key
        :return bytes:  Key that memcache accepts
        """
        if isinstance(key, str):
            key = key.encode("utf-8")

        if len(self.key_prefix) + len(key) <= 250 and all(0x21 <= byte <= 0x7e for byte in key):
            return key

        return b"hash-" + hashlib.sha256(key).hexdigest().encode("ascii")

    def _connect(self):
        """
        Connect a new memcache client for this thread

        :return MemcacheClient|None:  The client, or `None` if no memcache
        server is configured
        """
        if not self.server:
            return None

        client = MemcacheClient(self.server, serde=serde.pickle_serde, key_prefix=self.key_prefix,
                                connect_timeout=self.timeout, timeout=self.timeout)
        try:
            # connect, and check that memcache answers
            client.version()
        except MEMCACHE_ERRORS:
            client.close()
            raise

        self._connections.client = client
        return client

    def _command(self, command, failed=None, removes=False):
        """
        Run a command on memcache with this thread's client

        A client that ran into an error is not used again. The command is
        tried once more with a new client, which has a new connection: that is
        enough when memcache was restarted and closed the old connection. If
        the second try fails too, memcache is considered down until it can be
        reached and has been cleared again (see `_ready()`).

        Commands that change what is cached should wait for memcache to confirm
        them (`noreply=False`). By default pymemcache does not, and a command
        sent over a connection that memcache already closed is then lost
        without an error.

        :param callable command:  Function that runs the command on the client
        it is given
        :param failed:  What to return if memcache cannot be used
        :param bool removes:  Whether the command removes cached values
        :return:  What `command` returns, or `failed`
        """
        if not self._ready():
            return failed

        error = None
        for _ in range(2):
            try:
                client = getattr(self._connections, "client", None) or self._connect()
                if not client:
                    # no memcache server configured
                    return failed

                result = command(client)
            except MEMCACHE_ERRORS as e:
                self.close()
                if self._is_refusal(e, removes):
                    if self.logger and self._may_log("refused"):
                        self.logger.warning(f"Memcache refused a command ({self._describe_error(e)}). The value "
                                            f"concerned is read from the database instead of the cache.")
                    return failed

                error = e
                continue

            # memcache was probably restarted, which every thread runs into,
            # so do not log this for each
            if error and self.logger and self._may_log("reconnected"):
                self.logger.info(f"Memcache connection failed ({self._describe_error(error)}), but a new "
                                 f"connection works. Memcache was probably restarted.")
            return result

        self._failed(error)
        return failed

    @staticmethod
    def _is_refusal(error, removes):
        """
        Check if memcache works, but refused a command

        E.g. a value larger than memcache can store. Memcache can still be used
        for other values. A command that pymemcache refuses before sending it
        changes nothing in memcache, so that never counts as memcache failing.
        But when memcache itself answers a removal with an error, the value may
        still be cached, so that does count as memcache failing.

        :param Exception error:  The error memcache ran into
        :param bool removes:  Whether the command removes cached values
        :return bool:
        """
        if isinstance(error, MemcacheIllegalInputError):
            # refused by pymemcache, before it was sent
            return True
        if removes or isinstance(error, MemcacheUnexpectedCloseError):
            # a removal that may not have happened, or a closed connection
            return False
        return isinstance(error, (MemcacheClientError, MemcacheServerError))

    def _ready(self):
        """
        Check if memcache can be used

        After memcache fails it is down: it is not used until it can be reached
        again *and* has been cleared (see `clear()`), because a cached value
        that could not be removed in the meantime would otherwise be read
        again. A thread tries this every `retry_interval` seconds while the other
        threads read from the database meanwhile.

        :return bool:
        """
        if self._down_since is None:
            return True

        with self._lock:
            attempt_started = time.monotonic()
            if self._down_since is None:
                return True
            if attempt_started < self._next_attempt:
                return False

            # this thread makes the attempt; the others wait for the next one
            self._next_attempt = attempt_started + self.retry_interval
            down_since = self._down_since

        try:
            self.close()
            client = self._connect()
            if client:
                client.flush_all(noreply=False)
        except MEMCACHE_ERRORS as e:
            self.close()
            self._failed(e)
            return False

        with self._lock:
            # another thread may have run into an error while this attempt was
            # under way, after memcache was already cleared; then stay down and
            # clear it again on the next attempt
            if self._last_failure >= attempt_started:
                return False
            self._down_since = None

        if self.logger:
            self.logger.info(f"Memcache can be reached again after being down for "
                             f"{self._describe_duration(time.monotonic() - down_since)}. It was cleared and is used again.",
                             force_slack=True)
        return True

    def _failed(self, error):
        """
        Mark memcache as down after an error

        :param Exception error:  The error memcache ran into
        """
        message = None
        with self._lock:
            now = time.monotonic()
            self._last_failure = now
            if self._down_since is None:
                self._down_since = now
                self._next_attempt = now + self.retry_interval
                self._reminded_at = now
                message = f"Memcache cannot be reached ({self._describe_error(error)})."
            elif now - self._reminded_at >= self.reminder_interval:
                self._reminded_at = now
                down_for = self._describe_duration(now - self._down_since)
                message = f"Memcache still cannot be reached after {down_for} ({self._describe_error(error)})."

        # log outside the lock, since logging can take a while (e.g. when it
        # is sent to Slack)
        if message and self.logger:
            self.logger.warning(f"{message} Reading from the database instead, and trying memcache again every "
                                f"{self.retry_interval} seconds.")

    def _may_log(self, kind):
        """
        Check if a message of this kind may be logged now

        Used for messages that many threads would log at about the same time;
        each kind is logged at most once per minute.

        :param str kind:  Kind of message
        :return bool:
        """
        with self._lock:
            now = time.monotonic()
            last_logged = self._logged_at.get(kind)
            if last_logged is not None and now - last_logged < 60:
                return False
            self._logged_at[kind] = now
            return True

    @staticmethod
    def _describe_error(error):
        """
        Describe an error for a log message

        :param Exception error:
        :return str:
        """
        return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__

    @staticmethod
    def _describe_duration(seconds):
        """
        Describe a duration for a log message

        :param float seconds:
        :return str:
        """
        return f"{round(seconds)} seconds" if seconds < 120 else f"{round(seconds / 60)} minutes"
