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

# set a handler to clean the SCRATCHDIR once finished
trap "clean_scratch" TERM EXIT

export HMDIR="{{{STORAGE_ROOT}}}"
export BASEDR="$HMDIR/rtt_worker"
export HOME=$HMDIR
export RTT_PARALLEL={{{RTT_PARALLEL}}}

mkdir -p `dirname {{{LOG_ERR}}}` 2>/dev/null
mkdir -p `dirname {{{LOG_OUT}}}` 2>/dev/null

cd $HMDIR
. $HMDIR/pyenv-brno3.sh
pyenv local 3.7.1

cd "${BASEDR}"
# set -o pipefail
exec stdbuf -eL $HMDIR/.pyenv/versions/3.7.1/bin/python \\
  ./run_jobs.py $BASEDR/backend.ini \\
  --forwarded-mysql 1 \\
  --deactivate 1 \\
  --name {{{NAME}}} \\
  --id {{{ID}}} \\
  --location 'metacentrum' \\
  --longterm 0 \\
  --all-time 1 \\
  --run-time {{{RUN_TIME}}} \\
  --job-time {{{JOB_TIME}}} \\
  --pbspro \\
  --data-to-scratch \\
  2> {{{LOG_ERR}}} > {{{LOG_OUT}}}
  
# Copy logs back to FS
[[ -n "${SCRATCHDIR}" ]] && cp {{{LOG_ERR}}} {{{PERM_LOG_ERR}}}
[[ -n "${SCRATCHDIR}" ]] && cp {{{LOG_OUT}}} {{{PERM_LOG_OUT}}}

"""

"""
  --clean-cache 1 \\
  --clean-logs 1 \\
  x
"""


class JobGenerator:
    def __init__(self):
        self.args = None

    def work(self):
        if not self.args.job_dir:
            raise ValueError('Empty job dir')

        user = self.args.user
        if not user:
            user = os.getenv('PBS_O_LOGNAME', None)
        if not user:
            user = os.getenv('USER', None)
        if not user:
            raise ValueError('Could not determine user')

        storage_path = self.args.storage_full
        if not storage_path:
            storage_path = '/storage/%s/home/%s' % (self.args.storage, user)

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
            perm_log_err = os.path.abspath(os.path.join(log_dir, 'loge-%s.log' % worker_file_base))
            perm_log_out = os.path.abspath(os.path.join(log_dir, 'logo-%s.log' % worker_file_base))
            log_err = os.path.join('${SCRATCHDIR}', 'loge-%s.log' % worker_file_base) if self.args.scratch else perm_log_err
            log_out = os.path.join('${SCRATCHDIR}', 'logo-%s.log' % worker_file_base) if self.args.scratch else perm_log_out

            job_data = JOB_TEMPLATE
            job_data = job_data.replace('{{{STORAGE_ROOT}}}', storage_path)
            job_data = job_data.replace('{{{NAME}}}', worker_name)
            job_data = job_data.replace('{{{ID}}}', worker_id)
            job_data = job_data.replace('{{{RUN_TIME}}}', '%s' % (60*60*self.args.hr_job - 60*5))
            job_data = job_data.replace('{{{JOB_TIME}}}', '%s' % self.args.test_time)
            job_data = job_data.replace('{{{PERM_LOG_ERR}}}', perm_log_err)
            job_data = job_data.replace('{{{PERM_LOG_OUT}}}', perm_log_out)
            job_data = job_data.replace('{{{LOG_ERR}}}', log_err)
            job_data = job_data.replace('{{{LOG_OUT}}}', log_out)
            job_data = job_data.replace('{{{RTT_PARALLEL}}}', '%s' % (self.args.qsub_ncpu - 1))

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
            if self.args.scratch:
                qsub_args.append('scratch_local=%smb' % self.args.scratch_size)

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

        parser.add_argument('--scratch', dest='scratch', default=1, type=int,
                            help='Disable scratch by setting to 0')

        parser.add_argument('--scratch-size', dest='scratch_size', default=500, type=int,
                            help='Scratch size in MB')

        parser.add_argument('--user', dest='user', default=None,
                            help='User running under, overrides system default')

        parser.add_argument('--storage', dest='storage', default='brno3-cerit',
                            help='Cluster with the storage')

        parser.add_argument('--storage-full', dest='storage_full',
                            help='Full path to the storage root')

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
