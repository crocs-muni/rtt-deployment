import os
import time
import logging


logger = logging.getLogger(__name__)
EXPIRE_SECONDS_DEFAULT = 60 * 60 * 24


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

