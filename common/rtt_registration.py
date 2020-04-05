#!/usr/bin/python3

import paramiko
import os
import sys
import io
import subprocess
import shlex
from common.clilogging import *
from getpass import getpass

"""
This module will handle registering machines to database and storage.
When registering machine to database, new account in db for that machine
is created. When registering machine to storage, RSA key-pair is created on
the machine and the public part is appended to the storage "authorized_keys"
file.
"""


class LocalConnection:
    def __init__(self):
        pass

    def close(self):
        pass

    def exec_command(self, command, input=None):
        p = subprocess.Popen(shlex.split(command), bufsize=4096,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        stdout, stderr = p.communicate(input)
        return p.returncode, stdout, stderr


def exec_on_ssh(ssh, command, input=None):
    if isinstance(ssh, LocalConnection):
        exit_code, stdout, stderr = ssh.exec_command(command, input.encode("utf8") if input else None)
        return exit_code, stdout.decode("utf8").split("\n"), stderr.decode("utf8").split("\n")

    else:
        stdin, stdout, stderr = ssh.exec_command(command)
        if input:
            stdin.write(input)
            stdin.flush()

        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.readlines(), stderr.readlines()


def is_local_addr(addr):
    return addr in ['127.0.0.1', '::1', None, '']


def get_ssh_connection(def_username, address, port):
    if is_local_addr(address):
        return LocalConnection()

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


def get_db_command(username, password, command, db_host=None, db_port=None):
    creds = (' -u %s' % (username,)) if username else ''
    if password:
        creds += ' -p %s' % password

    cmd_host = (' -h %s' % db_host) if db_host else ''
    cmd_port = (' -P %s' % db_port) if db_port else ''

    res = "mysql {cr} {hst} {prt} -e {gr}".format(cr=creds, hst=cmd_host, prt=cmd_port, gr=command)
    return res


def get_db_reg_command(username, password, db_name, reg_name, reg_address, reg_pwd,
                       priv_select=False, priv_insert=False,
                       priv_update=False, priv_delete=False,
                       priv_create=False, priv_alter=False, priv_index=False,
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
    if priv_create:
        reg_rights += "CREATE,"
    if priv_alter:
        reg_rights += "ALTER,"
    if priv_index:
        reg_rights += "INDEX,"

    if reg_rights.endswith(','):
        reg_rights = reg_rights[:-1]

    grant_cmd = "\"GRANT {} ON {}.* TO '{}'@'{}'" \
                " IDENTIFIED BY '{}'\"" \
                .format(reg_rights, db_name, reg_name, reg_address, reg_pwd)
    return get_db_command(username, password, grant_cmd, db_host, db_port)


def register_db_user(server_acc, server_address, server_port,
                     reg_name, reg_pwd, reg_address, db_def_user, db_name,
                     priv_select=False, priv_insert=False,
                     priv_update=False, priv_delete=False,
                     priv_create=False, priv_alter=False, priv_index=False,
                     db_def_passwd=None, db_no_pass=False):

    print("\n\nRegistering user {} to database server on {}:{}..."
          .format(reg_name, server_address, server_port))

    def cmdfnc(*args, **kwargs):
        username = db_def_user
        password = db_def_passwd
        if username is None:
            print("Enter you credentials to database on server {}".format(server_address))
            username = input("Username (empty for {}): ".format(db_def_user))
            if len(username) == 0:
                username = db_def_user

        if password is None and not db_no_pass:
            password = getpass("MySQL Password (empty for none): ")

        command = get_db_reg_command(username, password, db_name, reg_name, reg_address, reg_pwd,
                                     priv_select, priv_insert, priv_update, priv_delete, priv_create,
                                     priv_alter, priv_index)
        return command

    return db_server_cmd(server_acc, server_address, server_port, command_fnc=cmdfnc)


def db_server_cmd(server_acc, server_address, server_port, command=None, command_fnc=None):
    ssh = get_ssh_connection(server_acc, server_address, server_port)
    if not ssh:
        print_error("Couldn't connect to database server, exit.")
        sys.exit(1)

    ctr = 0
    while True:
        ctr += 1
        curcmd = command
        if curcmd is None:
            curcmd = command_fnc(ctr)

        exit_code, stdout, stderr = exec_on_ssh(ssh, curcmd)
        if exit_code != 0:
            print("Command exit code: {}".format(exit_code))
            for e in stderr:
                print(e)

            opt = input("An error occurred during SQL command eval. Do you want to retry? (Y/N): ")
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
                                 pubkey_str, authorized_keys_path, password=None):
    print("\n\nRegistering public key to storage server {}".format(server_address))

    ssh = get_ssh_connection(server_acc, server_address, server_port)
    if not ssh:
        print_error("Couldn't connect to the server, exit.")
        sys.exit(1)

    command = "sudo -S su -c 'printf \"{0}\n\" >> {1}'".format(pubkey_str, authorized_keys_path)

    while True:
        if not is_local_addr(server_address) and not password:
            password = getpass("Enter sudo password (empty for none): ")

        inpt = password + "\n\n\n\n" if password else None
        exit_code, stdout, stderr = exec_on_ssh(ssh, command, inpt)

        if exit_code != 0:
            print("Command exit code: {}".format(exit_code))
            for e in stderr:
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

