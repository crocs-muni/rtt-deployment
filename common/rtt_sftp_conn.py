import configparser
import paramiko
from paramiko.sftp import SFTPError
import sys
import os
import time
from common.clilogging import *
import socket


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

        self.time_started = None
        self.time_transfer = None
        self.bytes_downloaded = 0
        self.last_bytes = 0
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

    def callback(self, bytes_transferred, total_bytes):
        new_bytes = bytes_transferred - self.last_bytes
        if new_bytes == 0:
            if self.first_zero_bytes_time is None:
                self.first_zero_bytes_time = time.time()
            self.num_zero_bytes += 1
        else:
            self.num_zero_bytes = 0

        # time_transfer = (time.time() - self.time_started) + 0.1
        # speed = bytes_transferred / time_transfer

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

                if time.time() - self.last_log > 30:
                    logger.debug("Download progress, time: %.2f, speed: %s, downloaded %s/%s"
                                 % (self.time_transfer, speed, self.bytes_downloaded, self.file_size))
                    self.last_log = time.time()

                if self.critical_speed and self.time_transfer > 60 and speed < self.critical_speed:
                    logger.info("Critical speed reached after %.2f sec, speed: %s, downloaded %s/%s"
                                % (self.time_transfer, speed, self.bytes_downloaded, self.file_size))
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
                    logger.error('Exc', e)
                    time.sleep(0.1)

        logger.info("Download process finished after %.2f sec, downloaded %s/%s, speed: %.2f MBps"
                    % (self.time_transfer, self.bytes_downloaded, self.file_size, self.bytes_downloaded / self.time_transfer / 1024/1024))

        success = self.bytes_downloaded >= self.file_size
        if not success:
            logger.info("Deleting dest file %s" % dest)
            os.remove(dest)
            raise DownloadFailedException()

        return success
        #return self.sftp.get(src, dest, callback=self.callback)


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
        sys.exit(1)

    try:
        pkey = paramiko.RSAKey.from_private_key_file(pkey_file, pkey_password)
        transport = paramiko.Transport((address, port))
        transport.connect(username=username, pkey=pkey)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get_channel().settimeout(60)
        return sftp
    except BaseException as e:
        print_error("Sftp connection: {}".format(e))
        sys.exit(1)
