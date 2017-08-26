#!/bin/bash
RUNNING="running.tmp"
exit_code=0
cat ../smirc/smirc.py | sed "s/^import irc\./import mock_irc\_/g;s/from systemd\.journal.*//g;s/.*JournalHandler.*/log.addHandler(logging.FileHandler('test.log'))/g" > smirc_test.py
rm -f *.log
rm -f $RUNNING
touch "$RUNNING"
python smirc_test.py --bot --config test.json &
echo "harness running..."
sleep 1
_test_command() {
echo "!$1" | python smirc_test.py --config test.json
}
_test_command "status"
python -c '#!/usr/bin/python
import smirc_test

smirc_test.run(config="test.json", arguments=["!mod"])
try:
    smirc_test.run(config="/invalid/path/config.json", arguments=["!mod"])
except smirc_test.SMIRCError as e:
    print(str(e))
    if str(e) == "no config file exists -> 1":
        exit(0)
exit(1)
'
if [ $? -ne 0 ]; then
    echo "module handling failed"
    exit_code=1
fi
echo "command(s) sent"
MAX=0
while [ -e $RUNNING ]; do
    sleep 5
    echo "waiting for tests to complete..."
    MAX=$((MAX+1))
    if [ $MAX -eq 5 ]; then
        echo "did not complete..."
        exit
    fi
done

_requires()
{
    for l in $(echo "${@:2}"); do
        echo "checking logs for $l (must != $1)"
        cat *.log | grep -q "^$l"
        if [ $? -ne $1 ]; then
            echo "failed required line for: $l"
            exit 1
        fi
    done
}
_requires 0 "alive connected __VERSION__ stopping !killkillkill #mock zmq loading module handle dict_keys"
_requires 1 "sending Resource Address will #original"
cat *.log | grep -F -q "dict_keys(['!mod', '!test'])"
if [ $? -ne 0 ]; then
    echo "missing required module/command loads"
    exit_code=1
fi

if [ $exit_code -gt 0 ]; then
    echo "test faillure reported"
    exit 1
fi
