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
import subprocess

VERS = "__VERSION__"

# globals
READY = False
HOST = True
JOINT = True
CONTEXT = None
RESET = False
KILLED = False
LAST_PONG = 0
RETRIES = 0
lock = threading.RLock()

# events
IND = "!"
STATUS = IND + "status"
DEBUG = IND + "debug"
HELP = IND + "help"
RESTART = IND + "restart"
KILL = IND + "killkillkill"

# help text
HELP_RAW = {}
HELP_RAW[STATUS] = "check status"
HELP_RAW[DEBUG] = "change debug output/toggle"
HELP_RAW[RESTART] = "restart the bot"
HELP_RAW[KILL] = "kill the bot (full service reboot)"
HELP_TEXT = "\n".join(["{} => {}".format(x, HELP_RAW[x]) for x in HELP_RAW])

# ZMQ thread
_STOP = 0
_TYPE = "type"
_DATA = "data"
_PRIV_TYPE = "priv"
_PUB_TYPE = "pub"

# logging
log = logging.getLogger('smirc')
log.addHandler(JournalHandler())
log.setLevel(logging.INFO)

def _send_lines(c, targets, val):
    """Send lines."""
    for item in val.split("\n"):
        if len(item.strip()) == 0:
            continue
        for target in targets:
            c.privmsg(target, item)


def on_connect(connection, event):
    """On connection."""
    log.info("connected")
    global READY
    global CONTEXT
    global RETRIES
    with lock:
        READY = True
        connection.join(CONTEXT.hostname)
        for item in CONTEXT.rooms:
            connection.join(item)
        RETRIES = 0


def _act(connection, event):
    """Perform an action."""
    global HOST
    global JOINT
    global CONTEXT
    global RESET
    global KILLED
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
                        elif event.target in CONTEXT.rooms:
                            HOST = True
                            JOINT = True
                        connection.privmsg(event.target, msg)
                if d == STATUS:
                    connection.privmsg(event.target, "alive: " + VERS)
                if d == HELP:
                    _send_lines(connection, [event.target], HELP_TEXT)
                    cmds = []
                    with lock:
                        for item in CONTEXT.commands:
                            cmds.append(item)
                    if len(cmds) > 0:
                        _send_lines(connection,
                                    [event.target],
                                    "\n".join(cmds))
                if d == RESTART or d.startswith(RESTART + " "):
                    log.info("restart requested...")
                    with lock:
                        parts = d.split(" ")
                        if event.target == CONTEXT.hostname or \
                           (len(parts) > 1 and CONTEXT.name in parts[1:]):
                               log.info('restart accepted...')
                               RESET = True
                if d == KILL:
                    with lock:
                        if event.target == CONTEXT.hostname:
                            log.info("killed.")
                            KILLED = True
                cmd = None
                subcmd = d.split(" ")
                if len(subcmd) > 0:
                    key = subcmd[0]
                    with lock:
                        if key in CONTEXT.commands:
                            cmd = CONTEXT.commands[key]
                    if cmd is not None:
                        _proc_cmd(cmd, connection, [event.target], subcmd[1:])


def _proc_cmd(cmd, connection, target, subcmd):
    """Process command."""
    try:
        cmds = []
        cmds.append(cmd)
        for item in subcmd:
            cmds.append(item)
        log.info(cmds)
        p = subprocess.Popen(cmds,
                             stderr=subprocess.STDOUT,
                             stdout=subprocess.PIPE)
        outs = None
        errs = None
        try:
            outs, errs = p.communicate(timeout=60)
        except TimeoutExpired:
            proc.kill()
            outs, errs = p.communicate()
        out = []
        if outs is not None:
            out.append(outs)
        if errs is not None:
            out.append(errs)
            log.info(out)
        if len(out) > 0:
            _send_lines(connection,
                        target,
                        "\n".join([x.decode("utf-8") for x in out]))
    except Exception as e:
        _send_lines(connection, target, "unable to execute command: " + str(e))


def on_message(connection, event):
    """On message received."""
    global CONTEXT
    do_action = False
    with lock:
        if event.target in [CONTEXT.hostname] + CONTEXT.rooms:
            do_action = True
    if do_action and event.type == "pubmsg":
        log.info(event)
        _act(connection, event)


def queue_thread(args, q, ctrl):
    """ZMQ receiving thread."""
    running = True
    while running:
        try:
            context = zmq.Context()
            socket = context.socket(zmq.REP)
            socket.bind("tcp://*:%s" % args.zmq)
            socket.RCVTIMEO = args.poll * 1000
            while True:
                try:
                    message = socket.recv_json()
                    socket.send_string("ack")
                    log.info(message)
                    q.put(message)
                    time.sleep(args.poll)
                except zmq.ZMQError as e:
                    if e.errno == zmq.EAGAIN:
                        try:
                            val = ctrl.get(block=False, timeout=args.poll)
                            # NOTE: only stop for now
                            running = False
                            raise Exception("bind reset")
                        except Empty:
                            pass
                    else:
                        raise Exception(str(z))
        except Exception as e:
            log.info("zmq error")
            log.info(e)
            if running:
                log.info("will rebind shortly")
                time.sleep(args.retry)
            else:
                log.info('stopping...')


class Ctx(object):
    """Context args."""

    def __init__(self):
        """Init the instance."""
        self.retry = 10
        self.poll = 3
        self.send = 60
        self.joint = "#fragmented"
        self.rooms = []


def get_args():
    """Get the arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        type=str,
                        default="/etc/epiphyte.d/smirc.json")
    parser.add_argument('--public', action="store_true")
    parser.add_argument('--private', action="store_true")
    parser.add_argument('--bot',
                        action="store_true")
    args, unknown = parser.parse_known_args()
    do_public = True
    do_private = True
    log.info(VERS)
    if args.public or args.private:
        do_public = args.public
        do_private = args.private
    if not os.path.exists(args.config):
        print("no config file exists")
        exit(1)
    commands = {}
    with open(args.config) as f:
        obj = Ctx()
        setattr(obj, "private", do_private)
        setattr(obj, "public", do_public)
        host = socket.gethostname()
        setattr(obj, "hostname", "#" + host)
        setattr(obj, "name", host + "-bot")
        setattr(obj, "bot", args.bot)
        cfg = json.loads(f.read())
        for k in cfg.keys():
            if k == "commands":
                sub = cfg[k]
                for sub_key in sub.keys():
                    commands[IND + sub_key] = sub[sub_key]
            else:
                setattr(obj, k, cfg[k])
        log.info(commands)
        setattr(obj, "commands", commands)
        if obj.rooms is None or \
           len(obj.rooms) == 0 or \
           obj.joint not in obj.rooms:
            obj.rooms.append(obj.joint)
        return (obj, unknown)


def sending(args, data):
    """Sending a message/client."""
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect("tcp://localhost:%s" % args.zmq)
    lines = data
    if lines is None or len(lines) == 0:
        lines = sys.stdin.readlines()
    datum = "".join(lines)
    linger = args.send * 1000
    socket.RCVTIMEO = linger
    result = False
    socket.setsockopt(zmq.LINGER, linger)
    try:
        obj = []
        if args.public:
            obj.append(_PUB_TYPE)
        if args.private:
            obj.append(_PRIV_TYPE)
        send_data = {}
        send_data[_TYPE] = obj
        send_data[_DATA] = datum
        socket.send_json(send_data, flags=zmq.NOBLOCK)
        ack = socket.recv(flags=zmq.NOBLOCK)
        log.info(ack)
        result = True
    except zmq.error.Again as z:
        log.info("sending error")
        log.info(z)
    return result


def on_pong(connection, event):
    """PONG received."""
    log.info(event)
    global LAST_PONG
    with lock:
        LAST_PONG = 0


def main():
    """Program entry."""
    global CONTEXT
    global READY
    global RESET
    global LAST_PONG
    global RETRIES
    global KILLED
    parsed = get_args()
    args = parsed[0]
    with lock:
        CONTEXT = args
    if not args.bot:
        if not sending(args, parsed[1]):
            exit(1)
        exit(0)
    q = Queue()
    ctrl = Queue()
    background_thread = threading.Thread(target=queue_thread, args=(args,
                                                                    q,
                                                                    ctrl))
    background_thread.start()
    while True:
        c = None
        with lock:
            RESET = False
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
            c.add_global_handler("pong", on_pong)
            do_ping = 0
            while True:
                react.process_once(timeout=args.poll)
                with lock:
                    if KILLED:
                        ctrl.put(_STOP)
                        log.info("kill kill kill")
                        exit(1)
                    if READY:
                        try:
                            val = q.get(block=False, timeout=args.poll)
                            targets = []
                            to = val[_TYPE]
                            if JOINT and _PUB_TYPE in to:
                                for item in args.rooms:
                                    targets.append(item)
                            if HOST and _PRIV_TYPE in to:
                                targets.append(args.hostname)
                            _send_lines(c, targets, val[_DATA])
                        except Empty:
                            pass
                    if RESET:
                        raise Exception("resetting...")
                    if LAST_PONG > 10:
                        LAST_PONG = 0
                        raise Exception("no recent pongs...")
                time.sleep(args.poll)
                do_ping += 1
                if do_ping > 10:
                    do_ping = 0
                    c.ping(args.hostname)
                    with lock:
                        LAST_PONG += 1
        except Exception as e:
            log.info(e)
            log.info("will retry shortly")
        if c is not None:
            try:
                c.disconnect("reconnecting...")
            except:
                pass
        kill = False
        with lock:
            kill = RETRIES > 3
            if not kill:
                RETRIES += 1
        if kill:
            log.info("killing process...")
            time.sleep(900)
            ctrl.put(_STOP)
            log.info("killed.")
            break
        else:
            time.sleep(args.retry)

if __name__ == "__main__":
    main()
