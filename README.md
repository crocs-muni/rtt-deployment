RTT

## Build chapters

### Massive deployment

Increase system limits for TCP connections, max user connections, etc
Critical for DB server and SSH gateway server:

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
pip install -U mysqlclient sarge requests shellescape coloredlogs filelock sshtunnel cryptography paramiko configparser pyinstaller
```

### Submit_experiment binary

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

### RTT worker dir

- Create `rtt_worker` dir from template
- Configure `backend.ini`, use absolute paths
- Configure `rtt_execution/rtt-settings.json`
- Rebuild RTT, use ph4r05 github fork with required additions (worker scratch dir, CLI params, e.g., mysql server; job ID setup, batched pvalue insert, faster regex, log files - append job ID)
- Rebuild dieharder statically


### RTT build
- copy /usr/include/cppconn and /usr/lib/x86_64-linux-gnu/libmysqlcppconn.* to the randomness-testing-toolkit dir
- edit Makefile, add -L.  to include local libmysqlcppconn.so
- for execution define LD_LIBRARY_PATH=. ./  if not compiled on metacentrum, otherwise compilation with updated makefile changes it, it works without setting LD_LIBRARY_PATH

```bash
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:`pwd`"
export LD_RUN_PATH="$LD_RUN_PATH:`pwd`"
export LDFLAGS="$LDFLAGS -L `pwd`"
make
./randomness-testing-toolkit   # works without LD_RUN_PATH when compiled with these ENVs set
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
ssh -i /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key rtt_storage@147.251.124.16 -L 3306:192.168.3.171:3306 -N

sshtunnel -K /storage/brno6/home/ph4r05/rtt_worker/credentials/storage_ssh_key -R 192.168.3.171:3306  -U rtt_storage 147.251.124.16 -S 'pSW^+kiogGeItQTwnqXt5gWVi<L?xf' -L :3336


# Job run
cd /storage/brno3-cerit/home/ph4r05/rtt_worker
. pyenv-brno3.sh
python ./run_jobs.py /storage/brno6/home/ph4r05/rtt_worker/backend.ini --forwarded-mysql 1 --clean-cache 1 --clean-logs 1 --deactivate 1 --name 'meta:tester' --id 'meta:tester' --location 'metacentrum' --longterm 0

# JobGen
python metacentrum.py --job-dir ../rtt-jobs --test-time $((60*60)) --hr-job 4 --num 1000

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

