import configparser
import paramiko
import sys
from common.clilogging import *


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
        return sftp
    except BaseException as e:
        print_error("Sftp connection: {}".format(e))
        sys.exit(1)
