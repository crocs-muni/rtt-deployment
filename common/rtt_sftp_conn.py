import configparser
import paramiko
from paramiko.sftp import SFTPError
import sys
import os
import time
from common.clilogging import *
import socket
from . import rtt_utils


class TimeLimitExceeded(Exception):
    pass


class DownloadFailedException(Exception):
    pass


class SftpDownloader(object):
    def __init__(self, sftp, critical_speed=None, critical_time_zero_bytes=None):
        self.sftp = sftp
        self.timeout = 60
        self.critical_speed = critical_speed
        self.critical_time_zero_bytes = critical_time_zero_bytes
        self.stat = None
        self.callback = None  # (SftpDownloader) -> Void

        self.time_started = None
        self.time_transfer = None
        self.bytes_downloaded = 0
        self.last_bytes = 0
        self.last_speed = 0
        self.num_zero_bytes = 0
        self.last_log = 0
        self.first_zero_bytes_time = None

    @property
    def file_size(self):
        return self.stat.st_size

    def reset(self):
        self.last_bytes = 0
        self.num_zero_bytes = 0
        self.first_zero_bytes_time = None
        self.time_started = None
        self.bytes_downloaded = 0
        self.time_transfer = 0
        self.last_log = 0

    def stat_file(self, src):
        self.stat = self.sftp.stat(src)

    def get(self, src, dest):
        self.reset()
        self.time_started = time.time()

        logger.info("Loading stats for file %s" % src)
        self.sftp.get_channel().settimeout(self.timeout)
        self.stat_file(src)
        self.last_log = time.time() - 10

        logger.debug("Opening file %s" % src)
        sfile = self.sftp.open(src, 'rb')
        logger.debug("File opened")

        sfile.settimeout(self.timeout)
        # sfile.setblocking(0)

        logger.info("Downloading %s, %s B (%.2f MB)" % (src, self.file_size, self.file_size/1024/1024))
        with open(dest, 'wb+') as cfile:
            while self.bytes_downloaded <= self.file_size:
                self.time_transfer = (time.time() - self.time_started) + 0.1
                speed = self.bytes_downloaded / self.time_transfer
                self.last_speed = speed

                if self.callback:
                    self.callback(self)

                if time.time() - self.last_log > 30:
                    logger.debug("Download progress, time: %.2f, speed: %.2f MBps, downloaded %s/%s  %.2f %%"
                                 % (self.time_transfer, speed / 1024 / 1024, self.bytes_downloaded, self.file_size,
                                    100.0 * self.bytes_downloaded / self.file_size))
                    self.last_log = time.time()

                if self.critical_speed and self.time_transfer > 60 and speed < self.critical_speed:
                    logger.info("Critical speed reached after %.2f sec, speed: %.2f MBps, downloaded %s/%s"
                                % (self.time_transfer, speed / 1024 / 1024, self.bytes_downloaded, self.file_size))
                    break

                if self.critical_time_zero_bytes and self.first_zero_bytes_time \
                        and self.critical_time_zero_bytes <= (time.time() - self.first_zero_bytes_time):
                    logger.info("No data received for quite a long time, terminating")
                    break

                try:
                    data = sfile.read(1024 * 4)
                    if not data:
                        logger.info("Empty data received, terminating transfer")
                        break

                    self.first_zero_bytes_time = None
                    self.bytes_downloaded += len(data)
                    cfile.write(data)

                except SFTPError as e:
                    self.first_zero_bytes_time = time.time()
                    time.sleep(0.1)

                except socket.timeout as e:
                    self.first_zero_bytes_time = time.time()
                    time.sleep(0.1)

                except Exception as e:
                    self.first_zero_bytes_time = time.time()
                    logger.error('Exc: %s' % (e,), exc_info=e)
                    time.sleep(0.1)

        logger.info("Download process finished after %.2f sec, downloaded %s/%s, speed: %.2f MBps"
                    % (self.time_transfer, self.bytes_downloaded, self.file_size, self.bytes_downloaded / self.time_transfer / 1024 / 1024))

        success = self.bytes_downloaded >= self.file_size
        if not success:
            logger.info("Deleting dest file %s" % dest)
            os.remove(dest)
            raise DownloadFailedException()

        return success
        #return self.sftp.get(src, dest, callback=self.callback)


class LockedDownloader(object):
    def __init__(self, sftp, path, acquire_timeout=60*60*8):
        self.sftp = sftp
        self.path = path  # Local path to download to
        self.path_downloaded_check = path + '.downloaded'
        self.locker = rtt_utils.FileLocker(self.path + '.lock', acquire_timeout=acquire_timeout)
        self.last_touch = 0

    def callback(self, downloader):
        tnow = time.time()
        df = tnow - self.last_touch
        if df > 2:
            self.locker.touch()
            self.last_touch = tnow

    def download(self, src, force=False):
        # Downloads src to the self.path
        # Lock first to check for the presence, need to lock to avoid race conditions,
        # other workers may be downloading the same file right now so file existence check would pass
        logger.info("Locking the download lock %s" % self.locker.path)
        self.locker.acquire()
        try:
            logger.info("Download lock %s acquired" % self.locker.path)
            # Locks eventually, timeout is 8 hours so it should happen only in very rare cases which aborts
            # the execution - exception propagates up as we don't know how to handle this at this
            # level of abstraction

            # After we lock, check for existence. If the file exists.
            if not force and os.path.exists(self.path) and os.path.exists(self.path_downloaded_check):
                logger.info("File already downloaded")
                return True

            # If forced or primary is missing, delete the downloaded marker.
            try:
                os.unlink(self.path_downloaded_check)
            except:
                pass

            # Otherwise, download the file with lock touching.
            logger.info("Downloading remote file {} into {}".format(src, self.path))
            downloader = SftpDownloader(self.sftp, critical_speed=1024, critical_time_zero_bytes=30)
            downloader.callback = self.callback
            downloader.get(src, self.path)

            # Download existence touch file
            # If downloader is terminated in the middle of the download, the download file is still there
            # but lock is expired, so we would manage to acquire the lock and check for file existence.
            # Thus we need this special flag file.
            with open(self.path_downloaded_check, 'a'):
                pass

            logger.info("Download complete.")
            return True
        finally:
            self.locker.release()
            logger.info("Download lock released")


class SSHParams(object):
    def __init__(self, host="127.0.0.1", port=22, user="rtt", pkey_file=None, pkey_pass=None):
        self.host = host
        self.port = port
        self.user = user
        self.pkey_file = pkey_file
        self.pkey_pass = pkey_pass


def ssh_load_params(main_cfg):
    try:
        address = main_cfg.get('Storage', 'Address')
        port = int(main_cfg.get('Storage', 'Port'))
        storage_cred_file = main_cfg.get('Storage', 'Credentials-file')
    except BaseException as e:
        print_error("Configuration file: {}".format(e))
        sys.exit(1)

    cred_cfg = configparser.ConfigParser()

    try:
        cred_cfg.read(storage_cred_file)
        if len(cred_cfg.sections()) == 0:
            print_error("Can't read credentials file: {}".format(storage_cred_file))
            sys.exit(1)

        username = cred_cfg.get('Credentials', 'Username')
        pkey_file = cred_cfg.get('Credentials', 'Private-key-file')
        pkey_password = cred_cfg.get('Credentials', 'Private-key-password')
    except BaseException as e:
        print_error("Credentials file: {}".format(e))
        raise ValueError("Could not load SSH params")  # sys.exit(1)

    return SSHParams(host=address, port=port, user=username, pkey_file=pkey_file, pkey_pass=pkey_password)


# Will create sftp connection to storage server
# Takes object main_cfg which is loaded
# configuration file. Config must contain
# section Storage with fields
# Address - IP address or host
# Port - port
# Credentials-file - path to file with login information
#   Must contain section Credentials with
#   fields Username, Private-key-file
#   (private part of key pair) and Private-key-password
def create_sftp_storage_conn(main_cfg):
    params = ssh_load_params(main_cfg)  # type: SSHParams
    return create_sftp_storage_conn_params(params)


def create_sftp_storage_conn_params(params: SSHParams):
    try:
        pkey = paramiko.RSAKey.from_private_key_file(params.pkey_file, params.pkey_pass)
        transport = paramiko.Transport((params.host, params.port))
        transport.connect(username=params.user, pkey=pkey)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get_channel().settimeout(60)
        return sftp
    except Exception as e:
        logger.error("Sftp connection: %s" % (e,), exc_info=e)
        raise
