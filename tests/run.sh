#!/bin/bash
RUNNING="running.tmp"
cat ../smirc.py | sed "s/^import irc\./import mock_irc\_/g;s/from systemd\.journal.*//g;s/.*JournalHandler.*/log.addHandler(logging.FileHandler('test.log'))/g" > smirc-test.py
rm -f *.log
rm -f $RUNNING
touch "$RUNNING"
python smirc-test.py --bot --config test.json &
echo "harness running..."
sleep 1
_test_command() {
    echo "!$1" | python smirc-test.py --config test.json
}

_test_command "status"
_test_command "mod"
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
_requires 0 "alive connected __VERSION__ stopping !killkillkill #mock zmq loading module"
_requires 1 "sending Resource Address will #original"
