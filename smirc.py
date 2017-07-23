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
log.addHandler(JournalHandler(SYSLOG_IDENTIFIER='smirc'))
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


def _act(connection, event, permitted):
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
                if d == STATUS:
                    connection.privmsg(event.target, "alive: " + VERS)
                    return
                if not permitted:
                    log.warn("not permitted user requested: " + d)
                    return
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
                            log.debug("killed.")
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
        log.debug(cmds)
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
            log.debug(out)
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
    permitted = False
    with lock:
        if event.target in [CONTEXT.hostname] + CONTEXT.rooms:
            do_action = True
            for source in CONTEXT.permitted:
                if source in event.source:
                    permitted = True
                    break
    if do_action and event.type == "pubmsg":
        log.debug(event)
        _act(connection, event, permitted)


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
                    log.debug(message)
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
            log.warning("zmq error")
            log.error(e)
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
    parser.add_argument('--to', type=str)
    parser.add_argument('--bot',
                        action="store_true")
    args, unknown = parser.parse_known_args()
    do_public = True
    do_private = True
    log.info(VERS)
    if args.public or args.private or args.to is not None and len(args.to) > 0:
        do_public = args.public
        do_private = args.private
    if not os.path.exists(args.config):
        print("no config file exists")
        exit(1)
    obj = Ctx()
    setattr(obj, "bot", args.bot)
    host = socket.gethostname()
    setattr(obj, "hostname", "#" + host)
    setattr(obj, "name", host + "-bot")
    setattr(obj, "private", do_private)
    setattr(obj, "public", do_public)
    setattr(obj, "to", args.to)
    setattr(obj, "permitted", [""])
    commands = {}
    load_config_context(obj, args.config, commands)
    local_cfg = args.config + ".local"
    if os.path.exists(local_cfg):
        log.info('loading local config')
        log.debug(local_cfg)
        load_config_context(obj, local_cfg, commands)
    log.debug(commands)
    setattr(obj, "commands", commands)
    if obj.rooms is None or \
       len(obj.rooms) == 0 or \
       obj.joint not in obj.rooms:
        obj.rooms.append(obj.joint)
    return (obj, unknown)


def load_config_context(obj, file_name, commands):
    """Load a config context into the object."""
    with open(file_name) as f:
        cfg = json.loads(f.read())
        for k in cfg.keys():
            if k == "commands":
                sub = cfg[k]
                for sub_key in sub.keys():
                    commands[IND + sub_key] = sub[sub_key]
            else:
                setattr(obj, k, cfg[k])


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
        if args.to is not None and len(args.to) > 0:
            if args.public and args.to:
                log.info("public overrides --to")
            else:
                obj.append(args.to)
        send_data = {}
        send_data[_TYPE] = obj
        send_data[_DATA] = datum
        socket.send_json(send_data)
        ack = socket.recv()
        log.debug(ack)
        result = True
    except zmq.error.Again as z:
        log.warning("sending error")
        log.error(z)
    return result


def on_pong(connection, event):
    """PONG received."""
    log.debug(event)
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
        code = 0
        if not sending(args, parsed[1]):
            code = 1
        exit(code)
    if args.server == "example.com":
        print("default/example server detected...exiting...")
        exit(1)
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
                        log.debug("kill kill kill")
                        exit(1)
                    if READY:
                        try:
                            val = q.get(block=False, timeout=args.poll)
                            targets = []
                            to = val[_TYPE]
                            if JOINT:
                                for item in args.rooms:
                                    if _PUB_TYPE in to:
                                        targets.append(item)
                                    elif item in to:
                                        targets.append(item)
                            if HOST and _PRIV_TYPE in to:
                                targets.append(args.hostname)
                            if len(targets) == 0:
                                log.warn("no targets for message")
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
            log.warning(e)
            log.error("will retry shortly")
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
