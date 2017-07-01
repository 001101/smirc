#!/usr/bin/python
"""IRC control/status bot."""
import irc.connection as conn
import ssl
import irc.client as client
import argparse
import time
import zmq
import threading
from multiprocessing import Queue
from queue import Empty
import os
import socket
import json
import sys
import logging
from systemd.journal import JournalHandler

# globals
READY = False
HOST = True
JOINT = True
CONTEXT = None
lock = threading.RLock()

# events
IND = "!"
STATUS = IND + "status"
DEBUG = IND + "debug"
HELP = IND + "help"

# help text
HELP_RAW = {}
HELP_RAW[STATUS] = "check status"
HELP_RAW[DEBUG] = "change debug output/toggle"
HELP_TEXT = "\n".join(["{} => {}".format(x, HELP_RAW[x]) for x in HELP_RAW])

# logging
log = logging.getLogger('smirc')
log.addHandler(JournalHandler())
log.setLevel(logging.INFO)

def _send_lines(c, targets, val):
    """Send lines."""
    for item in val.split("\n"):
        for target in targets:
            c.privmsg(target, item)


def on_connect(connection, event):
    """On connection."""
    log.info("connected")
    global READY
    global CONTEXT
    with lock:
        READY = True
        connection.join(CONTEXT.hostname)
        connection.join(CONTEXT.joint)


def _act(connection, event):
    """Perform an action."""
    global HOST
    global JOINT
    global CONTEXT
    data = event.arguments
    if data and len(data) > 0:
        for d in data:
            if d.startswith(IND):
                if d == DEBUG:
                    with lock:
                        msg = "public"
                        if CONTEXT.hostname == event.target:
                            msg = "private"
                            HOST = True
                            JOINT = False
                        elif CONTEXT.joint == event.target:
                            HOST = True
                            JOINT = True
                        connection.privmsg(event.target, msg)
                if d == STATUS:
                    connection.privmsg(event.target, "alive")
                if d == HELP:
                    _send_lines(connection, [event.target], HELP_TEXT)


def on_message(connection, event):
    """On message received."""
    global CONTEXT
    do_action = False
    with lock:
        if event.target in [CONTEXT.hostname, CONTEXT.joint]:
            do_action = True
    if do_action and event.type == "pubmsg":
        log.info(event)
        _act(connection, event)


def queue_thread(args, q):
    """ZMQ receiving thread."""
    while True:
        try:
            context = zmq.Context()
            socket = context.socket(zmq.REP)
            socket.bind("tcp://*:%s" % args.zmq)
            while True:
                message = socket.recv_string()
                log.info(message)
                q.put(message)
                socket.send_string("ack")
                time.sleep(args.poll)
        except Exception as e:
            log.info("will rebind shortly")
            log.info(e)
            time.sleep(args.retry)


class Ctx(object):
    """Context args."""

    def __init__(self):
        """Init the instance."""
        pass


def get_args():
    """Get the arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        type=str,
                        default="/etc/epiphyte.d/smirc.json")
    parser.add_argument('--bot',
                        action="store_true")
    args = parser.parse_args()
    if not os.path.exists(args.config):
        print("no config file exists")
        exit(1)
    with open(args.config) as f:
        obj = Ctx()
        host = socket.gethostname()
        setattr(obj, "hostname", "#" + host)
        setattr(obj, "name", host + "-bot")
        setattr(obj, "bot", args.bot)
        cfg = json.loads(f.read())
        for k in cfg.keys():
            setattr(obj, k, cfg[k])
        return obj


def sending(args):
    """Sending a message/client."""
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect("tcp://localhost:%s" % args.zmq)
    socket.send_string("".join(sys.stdin.readlines()))
    ack = socket.recv()
    log.info(ack)


def main():
    """Program entry."""
    global CONTEXT
    global READY
    args = get_args()
    with lock:
        CONTEXT = args
    if not args.bot:
        sending(args)
        return
    q = Queue()
    background_thread = threading.Thread(target=queue_thread, args=(args, q,))
    background_thread.start()
    while True:
        try:
            factory = conn.Factory(wrapper=ssl.wrap_socket)
            react = client.Reactor()
            server = react.server()
            c = server.connect(args.server,
                               args.port,
                               args.name,
                               password=args.password,
                               connect_factory=factory)
            c.add_global_handler("welcome", on_connect)
            c.add_global_handler("pubmsg", on_message)
            while True:
                react.process_once(timeout=args.poll)
                with lock:
                    if READY:
                        try:
                            val = q.get(block=False, timeout=args.poll)
                            targets = []
                            if JOINT:
                                targets.append(args.joint)
                            if HOST:
                                targets.append(args.hostname)
                            _send_lines(c, targets, val)
                        except Empty:
                            pass
                time.sleep(args.poll)
        except Exception as e:
            log.info(e)
            log.info("will retry shortly")
        time.sleep(args.retry)

if __name__ == "__main__":
    main()
