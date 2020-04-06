# RTT

Randomness testing toolkit runner and deployment scripts.

System consists of the following components:

## DB-server

- Runs MariaDB
- Stores all enqueued jobs, configurations, experiment results
- May be accessed directly via 3306 port if on local network
- Setup scripts access 3306 port via SSH tunnel connected to DB-server SSH

## Storage server

- Runs SSH server, chrooted for `rtt_storage` user
- Stores experiment input data. Data files are downloaded later by workers
- Works as SSH tunnel to the RTT infrastructure so remote workers can access DB-server over local network
- Has access to DB-server (cleanup old experiment data)

## Frontend server

- Users login via SSH, can submit experiments via CLI tool `submit_experiment`
- Contains helper tools, like `crypto-streams-v3.0`
- Admins can call `add_rtt_user.py` to add frontend users.
- Server has access to DB-server and storage server (for submission)

## Web server

- Hosts Django web application RTTWebInterface
- User can view experiments information here, results with high detail, structured. 
- Submission of experiments is possible via web interface
- Admin users can create new web users.
- Server has access to DB server. Web database can be hosted on DB-server or in a separate database locally on Web server.
- Using outdted Django 2.0.8, does not work with higher versions (needs to be ported)

## Worker / backend server

- Performs statistical tests, processes enqueued jobs, experiments.
- Multiple workers can be running. Multiple workers can run on one machine 
(even data storage is shareable, worker implements correct locking to avoid race conditions on the same machine)
- Worker can be longterm (if deployed on physical machines, always running), or short-term (for GRIDs, on-demand workers, PBSpro, Metacentrum)
- Workers can be deployed to grids (like Metacentrum), where thousands of workers can operate over shared network storage. 
Grid workers are using local scratch space for input data and battery scratch files.
- Workers have access to the Storage server via SSH and uses it also for a SSH tunnel to connect to the DB-server
- There is no scheduler, workers take work from job queue from database, using optimistic locking on jobs.
- One worker can run X tests in parallel (configurable, see below) from one battery. 
One worker performs one test at a time (e.g., one input, one battery)
- Workers send heartbeat (HB) info for jobs regularly. If there is no HB for a while, cleaner jobs assume worker is dead and job is set as pending again.
- If job fails too many times (10), job is not executed again (errors: input data can be already deleted, test segfaulting (should not happen))
- `run_jobs.py` is main worker script, loads jobs, executes tests. 
   - BoolTest jobs are executed via `booltest-rtt` wrapper (Python).
   - NIST, Diearder, Test U01 are executed via randomness-testing-toolkit app (all 4 in C++).
- `clean_cache.py` is cleaner job. At least one worker should be permanent with this script running. 
- Shortterm workers should not run `clean_cache.py`.
- Longterm workers starts jobs with `cron` and `flock`.
- All binaries are compiled with static dependencies to maximize binary portability between workers on a Grid. 


# Build / usage


## Docker all-in-one

Tldr: deploy all required services to one docker container.
Ideal for testing, one-user scenarios, debugging, reproducibility. 

We use debian-9 (stable OS, no major changes in the major version that could break something)

```bash
export TMP_RES_PATH="/tmp/rtt/"
export DEPLOYMENT_REPO_PATH="/path/to/this/deployment/repository"
mkdir -p $TMP_RES_PATH

# Run docker. 
# The "--cap-add SYS_PTRACE --cap-add sys_admin --security-opt seccomp:unconfined" is not required but enables
# debugging and running e.g., strace if something goes wrong. 
DOCKER_ID=$(docker run -idt \
    -v "$TMP_RES_PATH":"/result" \
    -v "$DEPLOYMENT_REPO_PATH":"/rtt-deployment" \
    -p 8000:80 -p 33060:3306 -p 32022:22 \
    -w "/rtt-deployment" \
    --cap-add SYS_PTRACE --cap-add sys_admin --security-opt seccomp:unconfined \
    debian:9)

# Update packages, install bare python3 + pip
docker exec $DOCKER_ID apt-get update -qq 2>/dev/null >/dev/null
docker exec $DOCKER_ID apt-get install python3-pip -qq --yes 

# Get shell and execute inside docker.
# You may be prompted to some questions, but 99% is automatic.
docker exec -it $DOCKER_ID /bin/bash
python3 deploy_database.py --config deployment_settings_local.ini --docker
python3 deploy_storage.py --config deployment_settings_local.ini --docker --local-db
python3 deploy_frontend.py --config deployment_settings_local.ini --docker --local-db --no-chroot --no-ssh-server --ph4
python3 deploy_web.py --config deployment_settings_local.ini --docker --local-db --ph4 
python3 deploy_backend.py 1  --config deployment_settings_local.ini --docker --local-db 

# Access http://127.0.0.1:80 on host, default admin credentials are admin:admin

# Misc:
#  - Create django user - another one. Can be done also via web interface.
cd /home/RTTWebInterface
./RTTWebInterfaceEnv/bin/python manage.py createsuperuser
```

### Massive deployment

Increase system limits for TCP connections, max user connections, etc
Critical for DB server and SSH storage/gateway server:

```bash
ulimit -Hn 65535 & ulimit -n 65535
cat /proc/sshd-id/limits
cat /proc/sys/net/core/somaxconn
cat /proc/sys/net/core/netdev_max_backlog

sysctl net.core.somaxconn=2048
cat /etc/security/limits.conf
* soft nofile 16384
* hard nofile 16384

cat /etc/sysctl.conf 
net.core.somaxconn=2048
```

### Python requirements 

We recommend Python 3.7.1

```bash
pip install -U mysqlclient sarge requests shellescape coloredlogs filelock sshtunnel cryptography paramiko configparser
```

### Submit_experiment binary

Building `submit_experiment` on your own:

```bash
cd /opt/rtt-submit-experiment
/bin/rm -rf build/ dist/
pyinstaller -F submit_experiment.py
mv dist/submit_experiment .
chgrp rtt_admin submit_experiment
chmod g+s submit_experiment
```


### DB backup & restore

Backup:
```bash
stdbuf -eL mysqldump --database rtt --complete-insert --compress --routines --triggers  --hex-blob  2> ~/backup-error.log | gzip > ~/backup_rtt_db.$(date +%F.%H%M%S).sql.gz
```

Restore:
```bash
cat backup_rtt_db.2019-08-12.180429.sql.gz | gunzip | mysql
```


## Metacentrum

Tldr: You need to build worker directory locally in Docker with same configuration as Metacentrum workers, then deploy 
built directory to the Metacentrum.

At first you need to prepare your working skeleton, i.e., installed backend/worker in your Metacentrum home dir. 

- Choose homedir of your choice, e.g. one with unlimited quota, `/storage/brno3-cerit/`. 
- Your worker dir is then `DEPLOY_PATH=/storage/brno3-cerit/home/$USERNAME/rtt_worker`, where `$USERNAME` is your Metacentrum login name.
Define it by yourself as you build it outside of Metacentrum.
- I assume you have your own `pyenv` installed, on version `3.7.1` at least. If not, install it to your local home, 
i.e., `/storage/brno3-cerit/home/$USERNAME`
- Configure your `deployment_settings.ini` accordingly:
  - Storage has to have public IP configured, storage server access is used also as SSH tunnel to RTT infrastructure network
  - MySQL-Database has internal IP address configured (accessed via tunnel)
  - Check `[Backend-metacentrum]`, configure `RTT-Files-dir` to be `/storage/brno3-cerit/home/$USERNAME/rtt_worker`
  - After you are done, check `[RTT-Binary]`, key `booltest-rtt-path`. 
  Make sure that it contains direct path that works without `pyenv` shims: e.g.: `/storage/brno3-cerit/home/ph4r05/.pyenv/versions/3.7.1/bin/booltest_rtt` 
- Tip: init `pyenv` after each login, but use direct paths to the python, e.g., `/storage/brno3-cerit/home/ph4r05/.pyenv/versions/3.7.1/bin/`
to avoid non-deterministic problems on Metacentrum (pyenv/NFS sometimes glitches, direct paths works fine).

Build backend/worker stuff locally using Docker. Metacentrum is using debian-9:

```
export TMP_RES_PATH="/tmp/rtt/result"
export DEPLOY_PATH="/path/from/deployment_settings.ini"
# export DEPLOY_PATH="/storage/brno3-cerit/home/ph4r05/rtt_worker"

export DEPLOYMENT_REPO_PATH="/path/to/this/repository"
mkdir -p $TMP_RES_PATH
DOCKER_ID=$(docker run -idt \
    -v "$TMP_RES_PATH":"/result" \
    -v "$DEPLOYMENT_REPO_PATH":"/rtt-deployment" \
    -w "/rtt-deployment" --cap-add SYS_PTRACE --cap-add sys_admin \
    --security-opt seccomp:unconfined --network=host debian:9)

docker exec $DOCKER_ID apt-get update -qq 2>/dev/null >/dev/null
docker exec $DOCKER_ID apt-get install python3-pip -qq --yes 

# Get shell inside container and build worker:
docker exec -it $DOCKER_ID /bin/bash
python3 deploy_backend.py metacentrum --metacentrum --no-db-reg --no-ssh-reg --no-email --no-cron

# Review configs:
find /storage/brno3-cerit/home/ph4r05/rtt_worker/ -type f \( -name '*.ini' -o -name '*.json' -o -name '*.cfg' \)

# Copy resulting skeleton to /results which is mapped to the host $TMP_RES_PATH
rsync -av $DEPLOY_PATH/ /result/
```

Once dir is ready, `rsync -av` it to the Metacentrum, absolute paths in configs have to match placement on the Metacentrum.
SSH private keys have to have `rw------` access rights, otherwise SSH refuses to use it. 

### Usage

```
cd $DEPLOY_PATH

# Generate worker jobs that will work on RTT jobs
#  - The command generates bash jobs to ../rtt-jobs
#  - Maximum time for one test is 4 hours (BoolTest takes long in all variants)
#  - hr-job = number of hours to allocate for worker job in PBS (4h is ideal for Metacentrum)
#  - num = number of workers to generate
#  - qsub-ncpu = number of vcpus per one worker. 4 -> 1 management, 3 parallel tests
#  - qsub-ram = total RAM for whole worker job (shared accross CPUs). If usage exceeds limit, job is terminated
#  - scratch size = amount of local space for job. Worker scratch and input data copied here. 
#     Has to be bigger than input file size + 100 MB
python metacentrum.py --job-dir ../rtt-jobs \
    --test-time $((4*60*60)) \
    --hr-job 4 \
    --num 100 \
    --qsub-ncpu 4 \
    --qsub-ram 8 \
    --scratch-size 8500

# Then inspect folder ../rtt-jobs, individual worker jobs have each one bash script
# plus there is enqueue_* script which enqueues all jobs to the queue (work starts in a while)
#  - Jobs are logging to scratch dir, after task finishes, it is copied to shared storage.
#  - If something goes wrong, you can directly SSH to worker machine and inspect logs in scratch manually 
#    (all info needed are in job details) https://metavo.metacentrum.cz/pbsmon2/user/ph4r05


# Testing
# Before starting whole batch, ask for one interactive job
qsub -l select=1:ncpus=4:mem=8gb::scratch_local=8500mb -l walltime=01:00:00 -I

# Once running, pick one job and execute it manually 
#  Benefit - change job script so logs are visible, not redirected to file. 
./rttw-.....sh

# Testing SSH tunnel:
#  Tests SSH port forwarding via storage server.
ssh -i /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key rtt_storage@147.251.124.16 \
    -L 3306:192.168.3.164:3306 -N

# Testing SSH tunnel with sshtunnel:
sshtunnel -K /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key -R 192.168.3.164:3306 \
  -U rtt_storage 147.251.124.16 -S 'pSW^+ki123123232312WVi<L?xf' -L :3336

# Job deactivate / kill
/storage/brno3-cerit/home/ph4r05/booltest/assets/cancel-jobs.sh  12587081 12587180
```

## Metacentrum - misc info for manual build / tuning

### RTT worker dir

- Create `rtt_worker` dir from template
- Configure `backend.ini`, use absolute paths
- Configure `rtt_execution/rtt-settings.json`
- Rebuild RTT, use ph4r05 github fork with required additions (worker scratch dir, CLI params, e.g., mysql server; job ID setup, batched pvalue insert, faster regex, log files - append job ID)
- Rebuild dieharder statically


### RTT build
- copy `/usr/include/cppconn` and `/usr/lib/x86_64-linux-gnu/libmysqlcppconn.*` to the randomness-testing-toolkit dir
- edit Makefile, add `-L.`  to include local `libmysqlcppconn.so`
- for execution define `LD_LIBRARY_PATH=.` ./  if not compiled on metacentrum, otherwise compilation with updated makefile changes it, it works without setting `LD_LIBRARY_PATH`

```bash
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:`pwd`"
export LD_RUN_PATH="$LD_RUN_PATH:`pwd`"
export LINK_PTHREAD="-Wl,-Bdynamic -lpthread"
export LINK_MYSQL="-lmysqlcppconn -L/usr/lib/x86_64-linux-gnu/libmariadbclient.a -lmariadbclient"
export LDFLAGS="$LDFLAGS -Wl,-Bdynamic -ldl -lz -Wl,-Bstatic -static-libstdc++ -static-libgcc -L `pwd`"
export CXXFLAGS="$CXXFLAGS -Wl,-Bdynamic -ldl -lz -Wl,-Bstatic -static-libstdc++ -static-libgcc -L `pwd`"
make
./randomness-testing-toolkit   # works without LD_RUN_PATH when compiled with these ENVs set

# Show dynamically linked dependencies
ldd randomness-testing-toolkit
```

Output: 
```
	linux-vdso.so.1 (0x00007fff72df5000)
	libdl.so.2 => /lib/x86_64-linux-gnu/libdl.so.2 (0x00007f30e07d8000)
	libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x00007f30e05be000)
	libpthread.so.0 => /lib/x86_64-linux-gnu/libpthread.so.0 (0x00007f30e03a1000)
	libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6 (0x00007f30e009d000)
	libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f30dfcfe000)
	/lib64/ld-linux-x86-64.so.2 (0x00007f30e09dc000)
```


### Dieharder static build
```bash
cd rtt_worker/rtt-statistical-batteries/dieharder-src/dieharder-3.31.1/
sed -i -e 's#dieharder_LDADD = .*#dieharder_LDFLAGS = -static\ndieharder_LDADD = -lgsl -lgslcblas -lm  ../libdieharder/libdieharder.la#g' dieharder/Makefile.am
sed -i -e 's#dieharder_LDADD = .*#dieharder_LDADD = -lgsl -lgslcblas -lm -static ../libdieharder/libdieharder.la#g' dieharder/Makefile.in

# build:
autoreconf -i && ./configure --enable-static --prefix=`pwd`/../install --enable-static=dieharder && make -j3 && make install
```


### Misc commands

```bash
./run_jobs.py /rtt_backend/backend.ini --forwarded-mysql 1 --clean-cache 1 --clean-logs 1 --deactivate 1 --name 'meta:tester' --id 'meta:tester' --location 'metacentrum' --longterm 0

# DB access
ssh -i /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key rtt_storage@147.251.124.16 -L 3306:192.168.3.164:3306 -N

sshtunnel -K /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key -R 192.168.3.164:3306  -U rtt_storage 147.251.124.16 -S 'pSW^+kiogGeItQTwnqXt5gWVi<L?xf' -L :3336


# Job run
cd /storage/brno3-cerit/home/ph4r05/rtt_worker
. pyenv-brno3.sh
python ./run_jobs.py /storage/brno6/home/ph4r05/rtt_worker/backend.ini --forwarded-mysql 1 --clean-cache 1 --clean-logs 1 --deactivate 1 --name 'meta:tester' --id 'meta:tester' --location 'metacentrum' --longterm 0

# JobGen @ metacentrum
python metacentrum.py --job-dir ../rtt-jobs --test-time $((4*60*60)) --hr-job 4 --num 100 --qsub-ncpu 4 --qsub-ram 8 --scratch-size 8500 

# Job deactivate
/storage/brno3-cerit/home/ph4r05/booltest/assets/cancel-jobs.sh  12587081 12587180

# Interactive job
qsub -l select=1:ncpus=2:mem=4gb -l walltime=04:00:00 -I
```

### Sync command

Adapt according to your user name / dir structure

```bash
# /storage/brno3-cerit/home/ph4r05

export HOST=skirit
export RTT_ROOT=/storage/brno3-cerit/home/ph4r05/rtt_worker

rsync -av --progress ~/workspace/rtt-deployment-openshift/common/ $HOST:$RTT_ROOT/common/ \
&& rsync -av --progress ~/workspace/rtt-deployment-openshift/files/run_jobs.py $HOST:$RTT_ROOT/ \
&& rsync -av --progress ~/workspace/rtt-deployment-openshift/files/clean_cache.py $HOST:$RTT_ROOT/clean_cache_backend.py \
&& rsync -av --progress ~/workspace/rtt-deployment-openshift/files/metacentrum.py $HOST:$RTT_ROOT \
&& ssh $HOST "chmod +x $RTT_ROOT/run_jobs.py; chmod +x $RTT_ROOT/clean_cache_backend.py;"
```

Sync scripts on all workers:

```bash
for HOST in rtt2w1 rtt2w2 rtt2w3 rtt2w4 rtt2w5; do 
    echo "=============================Syncing ${HOST}"
    rsync -av  --rsync-path="sudo rsync" --progress ~/workspace/rtt-deployment-openshift/common/ $HOST:/rtt_backend/common/
    rsync -av --rsync-path="sudo rsync" --progress ~/workspace/rtt-deployment-openshift/files/run_jobs.py $HOST:/rtt_backend/
    rsync -av --rsync-path="sudo rsync" --progress ~/workspace/rtt-deployment-openshift/files/clean_cache.py  $HOST:/rtt_backend/clean_cache_backend.py
    ssh $HOST 'sudo chown -R root:rtt_admin /rtt_backend/common; sudo chown -R root:rtt_admin /rtt_backend/run_jobs.py; sudo chmod +x /rtt_backend/run_jobs.py; sudo chown -R root:rtt_admin /rtt_backend/clean_cache_backend.py; sudo chmod +x /rtt_backend/clean_cache_backend.py; '
done
```

### BoolTest runner:

```bash
pip3 install booltest_rtt
```

Update `backend.ini`:

```ini
[RTT-Binary]
binary-path = /home/user/rtt_worker/rtt_execution/randomness-testing-toolkit
booltest-rtt-path = /home/user/.pyenv/versions/3.7.1/bin/booltest_rtt
```

Configuration in `rtt-settings.json`:

```json
{
    "booltest": {
        "default-cli": "--no-summary --json-out --log-prints --top 128 --no-comb-and --only-top-comb --only-top-deg --no-term-map --topterm-heap --topterm-heap-k 256 --best-x-combs 512",
        "strategies": [
            {
                "name": "v1",
                "cli": "",
                "variations": [
                    {
                        "bl": [128, 256, 384, 512],
                        "deg": [1, 2, 3],
                        "cdeg": [1, 2, 3],
                        "exclusions": []
                    }
                ]
            },
            {
                "name": "halving",
                "cli": "--halving",
                "variations": [
                    {
                        "bl": [128, 256, 384, 512],
                        "deg": [1, 2, 3],
                        "cdeg": [1, 2, 3],
                        "exclusions": []
                    }
                ]
            }
        ]
    }
}
```



