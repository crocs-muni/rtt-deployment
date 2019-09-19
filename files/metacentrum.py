#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import time
import hashlib
import subprocess
import sys


logger = logging.getLogger(__name__)
JOB_TEMPLATE = """#!/bin/bash

export HMDIR="/storage/brno3-cerit/home/ph4r05"
export BASEDR="$HMDIR/rtt_worker"
cd "${BASEDR}"

set -o pipefail
. $HMDIR/pyenv-brno3.sh
pyenv local 3.7.1

exec stdbuf -eL python ./run_jobs.py $BASEDR/backend.ini \\
  --forwarded-mysql 1 \\
  --clean-cache 1 \\
  --clean-logs 1 \\
  --deactivate 1 \\
  --name {{{NAME}}} \\
  --id {{{ID}}} \\
  --location 'metacentrum' \\
  --longterm 0 \\
  --all-time 1 \\
  --run-time {{{RUN_TIME}}} \\
  --job-time {{{JOB_TIME}}} \\
  2> {{{LOG_ERR}}} > {{{LOG_OUT}}}
"""


class JobGenerator:
    def __init__(self):
        self.args = None

    def work(self):
        if not self.args.job_dir:
            raise ValueError('Empty job dir')

        os.makedirs(self.args.job_dir, exist_ok=True)

        if self.args.log_dir:
            os.makedirs(self.args.log_dir, exist_ok=True)
        log_dir = self.args.log_dir if self.args.log_dir else self.args.job_dir

        # Generating jobs
        files = []
        batch_id = int(time.time())
        for idx in range(self.args.num):
            workid_base = 'rttw-%s-%04d' % (batch_id, idx)
            worker_id = hashlib.md5(workid_base.encode()).hexdigest()
            worker_name = 'meta:%s:%04d:%s' % (batch_id, idx, worker_id[:8])
            worker_file_base = '%s-%s' % (workid_base, worker_id[:8])

            job_data = JOB_TEMPLATE
            job_data = job_data.replace('{{{NAME}}}', worker_name)
            job_data = job_data.replace('{{{ID}}}', worker_id)
            job_data = job_data.replace('{{{RUN_TIME}}}', '%s' % (60*60*self.args.hr_job - 60*5))
            job_data = job_data.replace('{{{JOB_TIME}}}', '%s' % self.args.test_time)
            job_data = job_data.replace('{{{LOG_ERR}}}',
                                        os.path.abspath(os.path.join(log_dir, 'log2-%s.log' % worker_file_base)))
            job_data = job_data.replace('{{{LOG_OUT}}}',
                                        os.path.abspath(os.path.join(log_dir, 'log1-%s.log' % worker_file_base)))
            if '{{{' in job_data:
                raise ValueError('Missed placeholder')

            job_file = os.path.join(self.args.job_dir, '%s.sh' % worker_file_base)
            with open(os.open(job_file, os.O_CREAT | os.O_WRONLY, 0o700), 'w') as fh:
                fh.write(job_data)

            files.append(os.path.abspath(job_file))
            logger.debug('Generated file %s' % job_file)

        enqueue_path = os.path.join(self.args.job_dir, 'enqueue-meta-%s.sh' % int(time.time()))
        with open(os.open(enqueue_path, os.O_CREAT | os.O_WRONLY, 0o700), 'w') as fh:
            fh.write('#!/bin/bash\n\n')
            qsub_args = []
            if self.args.brno:
                qsub_args.append('brno=True')
            if self.args.cluster:
                qsub_args.append('cl_%s=True' % self.args.cluster)

            walltime = '%02d:00:00' % self.args.hr_job
            nprocs = self.args.qsub_ncpu
            qsub_args = ':'.join(qsub_args)
            qsub_args = (':%s' % qsub_args) if qsub_args != '' else ''
            for fn in files:
                fh.write('qsub -l select=1:ncpus=%s:mem=%sgb%s -l walltime=%s %s \n'
                         % (nprocs, self.args.qsub_ram, qsub_args, walltime, fn))

        if self.args.enqueue:
            logger.info('Enqueueing...')
            p = subprocess.Popen(enqueue_path, stdout=sys.stdout, stderr=sys.stderr, shell=True)
            p.wait()

    def main(self):
        logger.debug('App started')

        parser = argparse.ArgumentParser(description='PBSpro job generator for RTT workers')

        parser.add_argument('--debug', dest='debug', action='store_const', const=True,
                            help='enables debug mode')

        parser.add_argument('--verbose', dest='verbose', action='store_const', const=True,
                            help='enables verbose mode')

        #
        # Testbed related options
        #

        parser.add_argument('--job-dir', dest='job_dir', default=None,
                            help='Directory to put job files to')

        parser.add_argument('--log-dir', dest='log_dir', default=None,
                            help='Directory to put log files to')

        parser.add_argument('--brno', dest='brno', action='store_const', const=True, default=False,
                            help='qsub: Enqueue on Brno clusters')

        parser.add_argument('--cluster', dest='cluster', default=None,
                            help='qsub: Enqueue on specific cluster name, e.g., brno, elixir')

        parser.add_argument('--qsub-ncpu', dest='qsub_ncpu', default=2, type=int,
                            help='qsub:  Number of processors to allocate for a job')

        parser.add_argument('--qsub-ram', dest='qsub_ram', default=4, type=int,
                            help='qsub:  RAM to allocate in GB')

        parser.add_argument('--test-time', dest='test_time', default=60*60, type=int,
                            help='Number of seconds the single test will run (max)')

        parser.add_argument('--hr-job', dest='hr_job', default=24, type=int,
                            help='Job time to allocate in hours')

        parser.add_argument('--num', dest='num', default=1, type=int,
                            help='Number of jobs to generate')

        parser.add_argument('--enqueue', dest='enqueue', action='store_const', const=True, default=False,
                            help='Enqueues the generated batch via qsub after job finishes')

        self.args = parser.parse_args()
        self.work()


def main():
    jg = JobGenerator()
    jg.main()


if __name__ == "__main__":
    import coloredlogs
    coloredlogs.CHROOT_FILES = []
    coloredlogs.install(level=logging.DEBUG, use_chroot=False)
    main()
