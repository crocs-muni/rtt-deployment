import os
import time
import logging
import signal
import shutil
import hashlib
from filelock import Timeout, FileLock


logger = logging.getLogger(__name__)
EXPIRE_SECONDS_DEFAULT = 60 * 60 * 24
FILELOCK_FILTER_INSTALLED = False


def try_remove(path):
    if not path:
        return
    try:
        os.unlink(path)
    except:
        pass


def try_fnc(fnc):
    try:
        fnc()
    except:
        pass


def try_remove_rf(start):
    if not start:
        return
    return try_remove(lambda: shutil.rmtree(start, True))


def clean_log_files(log_root_dir, expire_seconds=EXPIRE_SECONDS_DEFAULT):
    cur_time = time.time()
    num_removed = 0
    size_removed = 0

    for root, dirs, files in os.walk(log_root_dir):
        for file in files:
            full_path = os.path.join(root, file)
            if not os.path.isfile(full_path):
                continue

            try:
                stat = os.stat(full_path)
                mtime = stat.st_mtime
                tdiff = cur_time - mtime
                if tdiff > expire_seconds:
                    logger.debug('Deleting expired file: %s, timediff: %s (%.2f h)' % (full_path, tdiff, tdiff/60/60))
                    os.remove(full_path)
                    num_removed += 1
                    size_removed += stat.st_size

            except Exception as e:
                logger.warning('Exception when analyzing %s' % full_path, e)

    return num_removed, size_removed


def get_associated_files(path):
    return [path + '.lock', path + '.lock.2', path + '.downloaded']


class FileLockerError(Exception):
    pass


class FileLocker(object):
    def __init__(self, path, acquire_timeout=60*60, lock_timeout=10, expire=120):
        self.path = path
        self.mlock_path = self.path + '.2'

        self.expire = expire
        self.lock_timeout = lock_timeout
        self.acquire_timeout = acquire_timeout

        self.primary_locker = FileLock(self.path, self.lock_timeout)

    def touch(self):
        try:
            with open(self.mlock_path, 'a'):
                try:
                    os.utime(self.mlock_path, None)  # => Set current time anyway
                except OSError:
                    pass
        except Exception as e:
            logger.error('Error touch the file', e)

    def mtime(self):
        try:
            return os.stat(self.mlock_path).st_mtime
        except:
            return 0

    def is_expired(self):
        mtime = self.mtime()
        return time.time() - mtime > self.expire

    def delete_timing(self):
        try:
            os.unlink(self.mlock_path)
        except:
            pass

    def release(self):
        self.delete_timing()
        self.primary_locker.release()

    def force_release(self):
        self.primary_locker.release(force=True)

    def acquire_try_once(self, _depth=0):
        if _depth > 0:
            logger.info("Acquire_try_once depth=%s" % _depth)
        if _depth > 2:
            return False

        # Try normal acquisition on the primary file
        try:
            self.primary_locker.acquire(self.lock_timeout, poll_intervall=0.5)
            self.touch()
            return True

        except Timeout:
            # Lock could not be acquired, check whether the timing file, whether
            # the locker is still alive. If not, force release and reacquire
            # to prevent starving on the deadly-locked resource.
            if self.is_expired():
                # Expired, release and force-acquire
                logger.info("Acquire timeout, timing file is expired, reacquire")
                self.force_release()

                # Try to re-acquire recursively
                return self.acquire_try_once(_depth + 1)

            else:
                return False

    def acquire(self, timeout=None):
        time_started = time.time()
        while True:
            res = self.acquire_try_once()
            if res:
                return True

            time_now = time.time()
            if timeout is not None and timeout < 0:
                time.sleep(0.01)
                continue
            if timeout is not None and timeout == 0:
                logger.info("Timeout, immediate")
                raise Timeout
            if timeout is None and time_now - time_started > self.acquire_timeout:
                logger.info("Timeout, self.acquire_timeout")
                raise Timeout
            if timeout is not None and timeout > 0 and time_now - time_started > timeout:
                logger.info("Timeout, defined")
                raise Timeout

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()


class GracefulKiller:
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        logger.info("Signal received: %s, frame: %s" % (signum, frame))
        self.kill_now = True

    def is_killed(self):
        return self.kill_now


class FileLockLogFilter(logging.Filter):
    def __init__(self, name="", *args, **kwargs):
        self.namex = name
        logging.Filter.__init__(self, *args, **kwargs)

    def filter(self, record):
        if record.levelno != logging.DEBUG:
            return 1

        try:
            # Parse messages are too verbose, skip.
            if record.name == "filelock":
                return 0

            return 1

        except Exception as e:
            logger.error("Exception in log filtering: %s" % (e,))

        return 1


def install_filelock_filter():
    global FILELOCK_FILTER_INSTALLED
    if FILELOCK_FILTER_INSTALLED:
        return

    for handler in logging.getLogger().handlers:
        handler.addFilter(FileLockLogFilter("hnd"))
    logging.getLogger().addFilter(FileLockLogFilter("root"))
    FILELOCK_FILTER_INSTALLED = True


def extend_lib_path(path):
    ld_path = os.getenv('LD_LIBRARY_PATH', None)
    return '%s:%s' % (ld_path, path) if ld_path else path


def is_lock_timeout_exception(e):
    if not e:
        return False
    try:
        if isinstance(e, (tuple, list)):
            return e[0] in [1205, 1213]
        s = str(e)
        if 'Deadlock found' in s:
            return True
        if 'Lock wait timeout exceeded' in s:
            return True

    except:
        pass

    return False


def hash_file_fh(hasher, fh):
    for byte_block in iter(lambda: fh.read(4*4096), b""):
        hasher.update(byte_block)
    return hasher


def hash_file(fname=None, fh=None, hasher=None):
    sha256_hash = hasher if hasher else hashlib.sha256()
    if fh:
        hash_file_fh(sha256_hash, fh)

    elif fname:
        with open(fname, "rb") as fh:
            hash_file_fh(sha256_hash, fh)

    else:
        raise ValueError("Input file not specified")

    return sha256_hash.digest()

