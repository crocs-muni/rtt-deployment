# RTT

Randomness testing toolkit runner and deployment scripts.

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
pip install -U mysqlclient sarge requests shellescape coloredlogs filelock sshtunnel cryptography paramiko configparser
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


### Metacentrum - prepare worker skeleton

```
export DEPLOY_PATH="/path/from/deployment_settings.ini"
# export DEPLOY_PATH="/storage/brno3-cerit/home/ph4r05/rtt_worker"

export DEPLOYMENT_REPO_PATH="/path/to/this/repository"
mkdir -p /tmp/rtt/result
DOCKER_ID=$(docker run -idt \
    -v "/tmp/rtt/result":"/result" \
    -v "$DEPLOYMENT_REPO_PATH":"/rtt-deployment" \
    -w "/rtt-deployment" --cap-add SYS_PTRACE --cap-add sys_admin \
    --security-opt seccomp:unconfined --network=host debian:9)

docker exec $DOCKER_ID apt-get update -qq 2>/dev/null >/dev/null
docker exec $DOCKER_ID apt-get install python3-pip -qq --yes 
docker exec $DOCKER_ID python3 deploy_backend.py metacentrum --metacentrum --no-db-reg --no-ssh-reg
docker exec $DOCKER_ID rsync -av $DEPLOY_PATH/ /result/

# To get shell:
docker exec -it $DOCKER_ID /bin/bash
```
