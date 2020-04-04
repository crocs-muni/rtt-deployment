#!/usr/bin/python3

import paramiko
import os
import sys
from common.clilogging import *
from getpass import getpass

"""
This module will handle registering machines to database and storage.
When registering machine to database, new account in db for that machine
is created. When registering machine to storage, RSA key-pair is created on
the machine and the public part is appended to the storage "authorized_keys"
file.
"""


def get_ssh_connection(def_username, address, port):
    while True:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print("Logging in to server {}:{}...".format(address, port))
        username = input("Username (empty for {}): ".format(def_username))
        if len(username) == 0:
            username = def_username

        print("\nTo log in as user {} to server {}:{} use:"
              .format(username, address, port))
        print("1. Private key")
        print("2. Password")
        print("Q. Exit the registration")
        opt = input("Select one (enter 1, 2 or Q): ")
        print()

        if opt == "1":
            print("You will be authenticated using private key.")
            pkey_path = input("Path to identity file (empty for ~/.ssh/id_rsa): ")
            password = getpass("Identity file password (empty for none): ")
            if len(pkey_path) == 0:
                pkey_path = os.path.abspath(os.path.expanduser("~/.ssh/id_rsa"))
            if len(password) == 0:
                password = None

            try:
                paramiko.RSAKey.from_private_key_file(pkey_path, password)
            except Exception as e:
                print_error("Private key file error (bad password?). {}".format(e))
                continue

        elif opt == "2":
            print("You will be authenticated using password.")
            pkey_path = None
            password = getpass("{}@{}:{} password (empty for none): "
                               .format(username, address, port))
            if len(password) == 0:
                password = None

        elif opt == "Q":
            print_info("Exiting registration.")
            return None

        else:
            print("Unknown option used!")
            continue

        try:
            ssh.connect(look_for_keys=False, allow_agent=False,
                        hostname=address, port=int(port), username=username,
                        key_filename=pkey_path, password=password)
            print_info("SSH connection successful.\n")
            return ssh
        except Exception as e:
            print_error("SSH connection failed (bad key, password?) {}".format(e))
            continue


def get_db_reg_command(username, password, db_name, reg_name, reg_address, reg_pwd,
                       priv_select=False, priv_insert=False,
                       priv_update=False, priv_delete=False,
                       db_host=None, db_port=None):
    reg_rights = ""
    if priv_select:
        reg_rights += "SELECT,"
    if priv_insert:
        reg_rights += "INSERT,"
    if priv_update:
        reg_rights += "UPDATE,"
    if priv_delete:
        reg_rights += "DELETE,"

    if reg_rights.endswith(','):
        reg_rights = reg_rights[:-1]

    creds = (' -u %s %s ' % (username, password)) if (username and password) else ''
    cmd_host = (' -h %s' % db_host) if db_host else ''
    cmd_port = (' -P %s' % db_port) if db_port else ''

    grant_cmd = "\"GRANT {} ON {}.* TO '{}'@'{}'" \
                " IDENTIFIED BY '{}'\"" \
                .format(reg_rights, db_name, reg_name, reg_address, reg_pwd)

    command = "mysql {cr} {hst} {prt} -e {gr}".format(cr=creds, hst=cmd_host, prt=cmd_port, gr=grant_cmd)
    return command


def register_db_user(server_acc, server_address, server_port,
                     reg_name, reg_pwd, reg_address, db_def_user, db_name,
                     priv_select=False, priv_insert=False,
                     priv_update=False, priv_delete=False):

    print("\n\nRegistering user {} to database server on {}:{}..."
          .format(reg_name, server_address, server_port))

    ssh = get_ssh_connection(server_acc, server_address, server_port)
    if not ssh:
        print_error("Couldn't connect to database server, exit.")
        sys.exit(1)

    while True:
        print("Enter you credentials to database on server {}".format(server_address))
        username = input("Username (empty for {}): ".format(db_def_user))
        if len(username) == 0:
            username = db_def_user

        password = getpass("Password (empty for none): ")
        if len(password) > 0:
            password = "-p" + password

        command = get_db_reg_command(username, password, db_name, reg_name, reg_address, reg_pwd,
                                     priv_select, priv_insert, priv_update, priv_delete)

        stdin, stdout, stderr = ssh.exec_command(command)

        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            print("Command exit code: {}".format(exit_code))
            for e in stderr.readlines():
                print(e)

            opt = input("An error occurred during registration. Do you want to retry? (Y/N): ")
            if opt == "Y" or opt == "y":
                continue
            else:
                print_info("It is possible that machine was not registered correctly."
                           "Other complications may happen later.")
                break

        else:
            break

    print_info("Registration into database successful!")
    ssh.close()


def add_authorized_key_to_server(server_acc, server_address, server_port,
                                 pubkey_str, authorized_keys_path):
    print("\n\nRegistering public key to storage server {}".format(server_address))

    ssh = get_ssh_connection(server_acc, server_address, server_port)
    if not ssh:
        print_error("Couldn't connect to the server, exit.")
        sys.exit(1)

    command = "sudo -S su -c 'printf \"{0}\n\" >> {1}'".format(pubkey_str, authorized_keys_path)

    while True:
        password = getpass("Enter sudo password (empty for none): ")
        stdin, stdout, stderr = ssh.exec_command(command)
        stdin.write(password + "\n\n\n\n")
        stdin.flush()

        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            print("Command exit code: {}".format(exit_code))
            for e in stderr.readlines():
                print(e)

            opt = input("An error occurred during registration. Do you want to retry? (Y/N): ")
            if opt == "Y" or opt == "y":
                continue
            else:
                print_info("It is possible that machine was not registered correctly."
                           "Other complications may happen later.")
                break

        else:
            break

    print_info("Registration into storage server successful!")
    ssh.close()

