#! /bin/bash

pyinstaller -F submit-experiment.py
mv dist/submit-experiment .
chown :rtt-admin submit-experiment
chmod 2775 submit-experiment
rm -rf build dist submit-experiment.spec
