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
from shlex import quote
import shellescape
from sarge import Capture, Feeder, run


logger = logging.getLogger(__name__)


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
            logger.error("Exception in log filtering: %s" % e)

        return 1


def install_sarge_filter():
    """
    Installs Sarge log filter to avoid long 1char debug dumps
    :return:
    """
    for handler in logging.getLogger().handlers:
        handler.addFilter(SargeLogFilter("hnd"))
    logging.getLogger().addFilter(SargeLogFilter("root"))


def sarge_sigint(proc, sig=signal.SIGINT):
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
    def __init__(self, cmd, args=None, stdout=None, stderr=None):
        self.cmd = cmd
        self.args = args
        self.on_finished = None
        self.on_output = None
        self.no_log_just_write = False
        self.log_out_during = True
        self.log_out_after = True
        self.stdout = stdout
        self.stderr = stderr

        self.using_stdout_cap = True
        self.using_stderr_cap = True
        self.ret_code = None
        self.out_acc = []
        self.err_acc = []
        self.is_running = False
        self.terminating = False
        self.thread = None

    def run(self):
        def preexec_function():
            os.setpgrp()

        args_str = (
            " ".join(self.args) if isinstance(self.args, (list, tuple)) else self.args
        )
        cmd = self.cmd
        if args_str and len(args_str) > 0:
            cmd += " " + args_str

        self.using_stdout_cap = self.stdout is None
        self.using_stderr_cap = self.stderr is None
        feeder = Feeder()
        p = run(
            cmd,
            input=feeder,
            async_=True,
            stdout=self.stdout or Capture(timeout=0.1, buffer_size=1),
            stderr=self.stderr or Capture(timeout=0.1, buffer_size=1),
            cwd=os.getcwd(),
            env=None,
            shell=True,
            preexec_fn=preexec_function,
        )

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

        def add_output(buffers, is_err=False):
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
                process_line(dst_cur[0])
                dst_cur[0] = ""

            for line in lines[1:-1]:
                process_line(line, is_err)

            dst_cur[0] = lines[-1] or ""

        try:
            while len(p.commands) == 0:
                time.sleep(0.15)

            self.is_running = True
            self.on_change()

            while p.commands[0].returncode is None:
                if self.using_stdout_cap:
                    out = p.stdout.read(-1, False)
                    if out:
                        add_output([out])

                if self.using_stderr_cap:
                    err = p.stderr.read(-1, False)
                    if err:
                        add_output([err], True)

                p.commands[0].poll()
                if self.terminating and p.commands[0].returncode is None:
                    logger.info("Terminating by sigint %s" % p.commands[0])
                    sarge_sigint(p.commands[0])
                    logger.info("Sigint sent")
                    p.close()
                    logger.info("Process closed")
                if (self.using_stdout_cap and not out) or (self.using_stderr_cap and err):
                    continue
                time.sleep(0.01)

            self.ret_code = p.commands[0].returncode
            if self.using_stdout_cap:
                add_output([p.stdout.read(-1, False)])
            if self.using_stderr_cap:
                add_output([p.stderr.read(-1, False)], True)
            self.is_running = False
            self.on_change()

            logger.info("Program ended with code: %s" % self.ret_code)
            logger.info("Command: %s" % cmd)
            if self.log_out_after:
                logger.info("Std out: %s" % "\n".join(self.out_acc))
                logger.info("Error out: %s" % "\n".join(self.err_acc))
            if self.on_finished:
                self.on_finished(self)

        except Exception as e:
            logger.error("Exception in wallet RPC command: %s" % e)
            # self.trace_logger.log(e)

    def on_change(self):
        pass

    def shutdown(self):
        if not self.is_running:
            return

        self.terminating = True
        time.sleep(1)

        # Terminating with sigint
        logger.info("Waiting for program to terminate...")
        self.terminating = True
        while self.is_running:
            time.sleep(0.1)

    def start(self):
        install_sarge_filter()
        self.thread = threading.Thread(target=self.run, args=())
        self.thread.setDaemon(False)
        self.thread.start()
