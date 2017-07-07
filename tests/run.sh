#!/bin/bash
RUNNING="running.tmp"
cat ../smirc.py | sed "s/^import irc\./import mock_irc\_/g;s/from systemd\.journal.*//g;s/.*JournalHandler.*/log.addHandler(logging.FileHandler('test.log'))/g" > smirc-test.py
rm -f *.log
rm -f $RUNNING
touch "$RUNNING"
python smirc-test.py --bot --config test.json &
sleep 1
echo "!status" | python smirc-test.py --config test.json
MAX=0
while [ -e $RUNNING ]; do
    sleep 5
    MAX=$((MAX+1))
    if [ $MAX -eq 5 ]; then
        echo "did not completed..."
        exit
    fi
done

_requires()
{
    for l in $(echo "${@:2}"); do
        cat *.log | grep -q "^$l"
        if [ $? -ne $1 ]; then
            echo "failed required line for: $l"
            exit 1
        fi
    done
}
_requires 0 "alive connected __VERSION__ stopping !killkillkill #mock zmq"
_requires 1 "sending Resource Address will"
