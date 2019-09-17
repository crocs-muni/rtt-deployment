#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Author: Dusan Klinec, ph4r05, 2018
# pip install shellescape sarge

import logging
import signal
import threading
import time
import sys
import os
import random
import socket
import typing
import tempfile
import paramiko
import sshtunnel
from shlex import quote
import shellescape
from sarge import Capture, Feeder, run
from . import rtt_sftp_conn
from . import rtt_utils

logger = logging.getLogger(__name__)
SARGE_FILTER_INSTALLED = False
RTT_BATTERIES = {
    'Dieharder': 'dieharder',
    'NIST Statistical Testing Suite': 'nist_sts',
    'TestU01 Alphabit': 'tu01_alphabit',
    'TestU01 Block Alphabit': 'tu01_blockalphabit',
    'TestU01 Crush': 'tu01_crush',
    'TestU01 Rabbit': 'tu01_rabbit',
    'TestU01 Small Crush': 'tu01_smallcrush',
}


def job_battery_to_experiment(bat):
    for keys in RTT_BATTERIES:
        if RTT_BATTERIES[keys] == bat:
            return keys
    raise ValueError('Key not found: %s' % bat)


def experiment_battery_to_job(bat):
    return RTT_BATTERIES[bat]


class SargeLogFilter(logging.Filter):
    """Filters out debugging logs generated by sarge - output capture. It is way too verbose for debug"""

    def __init__(self, name="", *args, **kwargs):
        self.namex = name
        logging.Filter.__init__(self, *args, **kwargs)

    def filter(self, record):
        if record.levelno != logging.DEBUG:
            return 1

        try:
            # Parse messages are too verbose, skip.
            if record.name == "sarge.parse":
                return 0

            # Disable output processing message - length of one character.
            msg = record.getMessage()
            if "queued chunk of length 1" in msg:
                return 0

            return 1

        except Exception as e:
            logger.error("Exception in log filtering: %s" % (e,))

        return 1


def install_sarge_filter():
    """
    Installs Sarge log filter to avoid long 1char debug dumps
    :return:
    """
    global SARGE_FILTER_INSTALLED
    if SARGE_FILTER_INSTALLED:
        return

    for handler in logging.getLogger().handlers:
        handler.addFilter(SargeLogFilter("hnd"))
    logging.getLogger().addFilter(SargeLogFilter("root"))
    SARGE_FILTER_INSTALLED = True


def sarge_sigint(proc, sig=signal.SIGTERM):
    """
    Sends sigint to sarge process
    :return:
    """
    proc.process_ready.wait()
    p = proc.process
    if not p:  # pragma: no cover
        raise ValueError("There is no subprocess")
    p.send_signal(sig)


def escape_shell(inp):
    """
    Shell-escapes input param
    :param inp:
    :return:
    """
    try:
        inp = inp.decode("utf8")
    except:
        pass

    try:
        return shellescape.quote(inp)
    except:
        pass

    quote(inp)


class AsyncRunner:
    def __init__(self, cmd, args=None, stdout=None, stderr=None, cwd=None, shell=True, env=None):
        self.cmd = cmd
        self.args = args
        self.on_finished = None
        self.on_output = None
        self.on_tick = None
        self.no_log_just_write = False
        self.log_out_during = True
        self.log_out_after = True
        self.stdout = stdout
        self.stderr = stderr
        self.cwd = cwd
        self.shell = shell
        self.env = env
        self.preexec_setgrp = False

        self.using_stdout_cap = True
        self.using_stderr_cap = True
        self.ret_code = None
        self.out_acc = []
        self.err_acc = []
        self.feeder = None
        self.proc = None
        self.is_running = False
        self.was_running = False
        self.terminating = False
        self.thread = None

    def run(self):
        try:
            self.run_internal()
        except Exception as e:
            self.is_running = False
            logger.error("Unexpected exception in runner: %s" % (e,))
        finally:
            self.was_running = True

    def __del__(self):
        self.deinit()

    def deinit(self):
        rtt_utils.try_fnc(lambda: self.feeder.close())

        if not self.proc:
            return

        if self.using_stdout_cap:
            rtt_utils.try_fnc(lambda: self.proc.stdout.close())

        if self.using_stderr_cap:
            rtt_utils.try_fnc(lambda: self.proc.stderr.close())

        rtt_utils.try_fnc(lambda: self.proc.close())

    def run_internal(self):
        def preexec_function():
            os.setpgrp()

        cmd = self.cmd
        if self.shell:
            args_str = (
                " ".join(self.args) if isinstance(self.args, (list, tuple)) else self.args
            )

            if isinstance(cmd, (list, tuple)):
                cmd = " ".join(cmd)

            if args_str and len(args_str) > 0:
                cmd += " " + args_str

        else:
            if self.args and not isinstance(self.args, (list, tuple)):
                raise ValueError("!Shell requires array of args")
            if self.args:
                cmd += self.args

        self.using_stdout_cap = self.stdout is None
        self.using_stderr_cap = self.stderr is None
        self.feeder = Feeder()

        logger.info("Starting command %s in %s" % (cmd, self.cwd))

        run_args = {}
        if self.preexec_setgrp:
            run_args['preexec_fn'] = preexec_function

        p = run(
            cmd,
            input=self.feeder,
            async_=True,
            stdout=self.stdout or Capture(timeout=0.1, buffer_size=1),
            stderr=self.stderr or Capture(timeout=0.1, buffer_size=1),
            cwd=self.cwd,
            env=self.env,
            shell=self.shell,
            **run_args,
        )

        self.proc = p
        self.ret_code = 1
        self.out_acc, self.err_acc = [], []
        out_cur, err_cur = [""], [""]

        def process_line(line, is_err=False):
            dst = self.err_acc if is_err else self.out_acc
            dst.append(line)
            if self.log_out_during:
                if self.no_log_just_write:
                    dv = sys.stderr if is_err else sys.stdout
                    dv.write(line + "\n")
                    dv.flush()
                else:
                    logger.debug("Out: %s" % line.strip())
            if self.on_output:
                self.on_output(self, line, is_err)

        def add_output(buffers, is_err=False, finish=False):
            buffers = [x.decode("utf8") for x in buffers]
            lines = [""]

            dst_cur = err_cur if is_err else out_cur
            for x in buffers:
                clines = [v.strip("\r") for v in x.split("\n")]
                lines[-1] += clines[0]
                lines.extend(clines[1:])

            dst_cur[0] += lines[0]
            nlines = len(lines)
            if nlines > 1:
                process_line(dst_cur[0], is_err)
                dst_cur[0] = ""

            for line in lines[1:-1]:
                process_line(line, is_err)

            dst_cur[0] = lines[-1] or ""
            if finish and lines[-1]:
                process_line(lines[-1], is_err)

        try:
            while len(p.commands) == 0:
                time.sleep(0.15)

            logger.info("Program started, progs: %s" % len(p.commands))
            if p.commands[0] is None:
                self.is_running = False
                self.was_running = True
                logger.error("Program could not be started")
                return

            self.is_running = True
            self.on_change()

            while p.commands[0] and p.commands[0].returncode is None:
                if self.using_stdout_cap:
                    out = p.stdout.read(-1, False)
                    if out:
                        add_output([out])

                if self.using_stderr_cap:
                    err = p.stderr.read(-1, False)
                    if err:
                        add_output([err], True)

                if self.on_tick:
                    self.on_tick(self)

                p.commands[0].poll()
                if self.terminating and p.commands[0].returncode is None:
                    logger.info("Terminating by sigint %s" % p.commands[0])
                    sarge_sigint(p.commands[0], signal.SIGTERM)
                    sarge_sigint(p.commands[0], signal.SIGINT)
                    logger.info("Sigint sent")
                    logger.info("Process closed")

                if (self.using_stdout_cap and not out) or (self.using_stderr_cap and err):
                    continue
                time.sleep(0.1)

            logger.info("Runner while ended")
            p.wait()
            self.ret_code = p.commands[0].returncode if p.commands[0] else -1

            if self.using_stdout_cap:
                add_output([p.stdout.read(-1, False)], finish=True)
                rtt_utils.try_fnc(lambda: p.stdout.close())

            if self.using_stderr_cap:
                add_output([p.stderr.read(-1, False)], True, finish=True)
                rtt_utils.try_fnc(lambda: p.stderr.close())

            self.was_running = True
            self.is_running = False
            self.on_change()

            logger.info("Program ended with code: %s" % self.ret_code)
            logger.info("Command: %s" % cmd)

            if self.log_out_after:
                logger.info("Std out: %s" % "\n".join(self.out_acc))
                logger.info("Error out: %s" % "\n".join(self.err_acc))

        except Exception as e:
            self.is_running = False
            logger.error("Exception in async runner: %s" % (e,))

        finally:
            self.was_running = True
            rtt_utils.try_fnc(lambda: self.feeder.close())
            rtt_utils.try_fnc(lambda: self.proc.close())

            if self.on_finished:
                self.on_finished(self)

    def on_change(self):
        pass

    def shutdown(self):
        if not self.is_running:
            return

        self.terminating = True
        time.sleep(1)

        # Terminating with sigint
        logger.info("Waiting for program to terminate...")
        while self.is_running:
            time.sleep(0.1)
        logger.info("Program terminated")
        self.deinit()

    def start(self):
        install_sarge_filter()
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.setDaemon(False)
        self.thread.start()
        self.terminating = False
        self.is_running = False
        while not self.is_running and not self.was_running:
            time.sleep(0.1)
        return self


def get_rtt_runner(rtt_args, cwd):
    rtt_env = {'LD_LIBRARY_PATH': rtt_utils.extend_lib_path(cwd)}
    async_runner = AsyncRunner(rtt_args, cwd=cwd, shell=False, env=rtt_env)
    async_runner.log_out_after = False
    async_runner.preexec_setgrp = True
    return async_runner


class SSHForwarder:
    def __init__(self, ssh_params: rtt_sftp_conn.SSHParams, remote_server: str, remote_port: int, local_port=None):
        self.ssh_params = ssh_params
        self.remote_server = remote_server
        self.remote_port = remote_port
        self.local_port = local_port

    def start(self):
        raise ValueError('Not implemented')

    def shutdown(self):
        raise ValueError('Not implemented')


class SSHForwarderPython(SSHForwarder):
    def __init__(self, ssh_params: rtt_sftp_conn.SSHParams, remote_server: str, remote_port: int, local_port=None):
        super().__init__(ssh_params, remote_server, remote_port, local_port)

        self.is_running = False
        self.terminating = False
        self.thread = None

    def run(self):
        logger.info("Establishing SSH tunnel...")
        local_args = {} if not self.local_port else {'local_bind_address': ('0.0.0.0', self.local_port)}
        with sshtunnel.open_tunnel(
                (self.ssh_params.host, self.ssh_params.port),
                ssh_username=self.ssh_params.user,
                ssh_pkey=self.ssh_params.pkey_file,
                ssh_private_key_password=self.ssh_params.pkey_pass,
                remote_bind_address=(self.remote_server, self.remote_port),
                **local_args
        ) as tunnel:
            self.local_port = tunnel.local_bind_port
            self.is_running = True
            logger.info("SSH tunnel established, port: %s" % self.local_port)

            while not self.terminating:
                time.sleep(0.5)

            self.is_running = False
            logger.info("Closing SSH tunnel")

    def start(self):
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.setDaemon(False)
        self.thread.start()
        self.terminating = False
        self.is_running = False
        while not self.is_running:
            time.sleep(0.1)
        return self

    def shutdown(self):
        if not self.is_running:
            return
        self.terminating = True
        time.sleep(1)

        # Terminating with sigint
        logger.info("Waiting for ssh tunnel to terminate...")
        while self.is_running:
            time.sleep(0.1)


def bind_random_port():
    for _ in range(5000):
        port = random.randrange(20000, 65535)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(('127.0.0.1', port))
            return s, port

        except socket.error as e:
            s.close()
    raise ValueError('Binding took too long')


def try_to_connect(host, port, timeout=15):
    tstart = time.time()
    while True:
        if time.time() - tstart > timeout:
            raise ValueError('Could not connect in time')

        s = socket.socket()
        s.settimeout(5)
        try:
            s.connect((host, port))
            return s
        except socket.error as exc:
            time.sleep(0.1)
            continue


class SSHForwarderLinux(SSHForwarder):
    def __init__(self, ssh_params: rtt_sftp_conn.SSHParams, remote_server: str, remote_port: int, local_port=None):
        super().__init__(ssh_params, remote_server, remote_port, local_port)
        self.on_bind_error = None
        self.do_setsid = True

        self.reservation_socket = None
        self.runner = None  # type: typing.Optional[AsyncRunner]
        self.ssh_passwd_asked = False
        self.ssh_passwd_entered = False
        self.bind_error = False
        self.ask_pass_path = None
        self.first_tick = None
        self.script_path = None
        self.pid_path = None

    def __del__(self):
        logger.info("SSH shutdown on delete (dirty)")
        self.shutdown()

    def create_runner(self):
        if self.local_port is None:
            self.reservation_socket, self.local_port = bind_random_port()
            logger.info("Reserving random local port: %s" % self.local_port)

        args = [
            '-i', '\'%s\'' % self.ssh_params.pkey_file,
            '-L', '%s:%s:%s' % (self.local_port, self.remote_server, self.remote_port),
            '-N',
            '-oLogLevel=error',
            '-oStrictHostKeyChecking=no',
            '-oUserKnownHostsFile=/dev/null',
            '-o ConnectTimeout=30',
            '-p', '%s' % self.ssh_params.port,
            '\'%s\'@%s' % (self.ssh_params.user, self.ssh_params.host),
        ]

        args_str = ' '.join(args)
        cmd = 'ssh %s' % args_str

        if self.do_setsid:
            self.create_shell_run_script(cmd)
            cmd = 'setsid bash %s' % self.script_path

        env = {
            'DISPLAY': ':0',
            'SSH_ASKPASS': self.ask_pass_path
        }

        logger.info("Creating runner with: %s, env: %s" % (cmd, env))
        self.runner = AsyncRunner(cmd, shell=True, env=env)
        self.runner.on_output = self.on_ssh_line
        self.runner.on_tick = self.on_ssh_tick
        self.runner.on_finished = self.on_ssh_finish

    def on_ssh_line(self, runner, line: str, is_error):
        low = line.lower().strip()
        if low.startswith('enter pass'):
            self.ssh_passwd_asked = True

        if low.startswith('bind: address al'):
            self.bind_error = True
            if self.on_bind_error:
                self.on_bind_error()

    def on_ssh_tick(self, runner):
        if not self.first_tick:
            self.first_tick = time.time()

        if time.time() - self.first_tick > 10:
            self.try_delete_shell_script()

        if self.ssh_passwd_asked and not self.ssh_passwd_entered:
            self.runner.feeder.feed(self.ssh_params.pkey_pass)
            self.runner.feeder.feed("\n")
            self.ssh_passwd_entered = True
            logger.info("Key password entered")

    def on_ssh_finish(self, runner):
        logger.info("SSH tunnel finished")
        self.try_delete_shell_script()

    def create_shell_run_script(self, cmd):
        old_mask = os.umask(0)

        temp = tempfile.NamedTemporaryFile()
        self.script_path = temp.name
        temp.close()

        temp = tempfile.NamedTemporaryFile()
        self.pid_path = temp.name
        temp.close()

        logger.info('Creating SSH run script: %s, pid file: %s, cmd: %s'
                    % (self.script_path, self.pid_path, cmd))

        with open(os.open(self.script_path, os.O_CREAT | os.O_WRONLY, 0o700), 'w') as fh:
            fh.write('#!/bin/bash\n')
            fh.write('%s &\n' % cmd)
            fh.write('echo $! > %s\n' % self.pid_path)
        os.umask(old_mask)

    def create_shell_script(self):
        old_mask = os.umask(0)

        temp = tempfile.NamedTemporaryFile()
        self.ask_pass_path = temp.name
        temp.close()

        logger.info('Creating SSH ask script: %s' % self.ask_pass_path)
        with open(os.open(self.ask_pass_path, os.O_CREAT | os.O_WRONLY, 0o700), 'w') as fh:
            fh.write('#!/bin/bash\n')
            fh.write('echo "%s"\n' % self.ssh_params.pkey_pass)
            fh.write('/bin/rm "%s" >/dev/null 2>/dev/null\n' % self.ask_pass_path)

        os.umask(old_mask)

    def try_delete_shell_script(self):
        try:
            if self.ask_pass_path and os.path.exists(self.ask_pass_path):
                logger.info("Deleting ASK pass script %s" % self.ask_pass_path)
                os.unlink(self.ask_pass_path)
            self.ask_pass_path = None
        except:
            pass

    def start(self):
        self.create_shell_script()
        self.create_runner()
        if self.reservation_socket:
            self.reservation_socket.close()
            logger.info("Reservation socket closed, race begins...")

        self.runner.start()

        # Connection test
        try:
            logger.info("SSH started, waiting for port availability")
            s = try_to_connect('127.0.0.1', self.local_port, 60)
            s.close()
            time.sleep(1)

        except Exception as e:
            logger.error('Could not start SSH port forwarding in the given time limit, aborting execution')
            self.runner.shutdown()
            raise ValueError('Could not start SSH tunneling')

    def shutdown(self):
        logger.info("Shutting down SSH forwarder")

        if self.pid_path:
            logger.info("PID file found %s, trying to terminate..." % self.pid_path)
            try:
                pid = None
                with open(self.pid_path) as fh:
                    pid = int(fh.read().strip())
                
                logger.info("Sending SIGTERM to PID %s" % pid)
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)

            except Exception as e:
                logger.error("Exception when terminating running ssh %s" % (e,))

        logger.info("SSH runner shutdown")
        self.runner.shutdown()

        logger.info("SSH runner cleanup")
        rtt_utils.try_remove(self.pid_path)
        rtt_utils.try_remove(self.script_path)
        rtt_utils.try_remove(self.ask_pass_path)
        self.pid_path = None
        self.script_path = None
        self.ask_pass_path = None
        logger.info("SSH Shutdown finished")

