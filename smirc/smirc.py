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
import importlib.util

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
REPORTED_IN = False
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

# Command types
_CMD_TYPE = "commands"
_MOD_TYPE = "modules"

# CLI flags
_PUBLIC_FLAG = "--public"
_PRIVATE_FLAG = "--private"
_TO_FLAG = "--to"
_BOT_FLAG = "--bot"
_CONFIG_FLAG = "--config"

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
                # NOTE: Commands after this section require permission
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


def _proc_cmd(cmd_obj, connection, target, subcmd):
    """Process command."""
    try:
        if not cmd_obj.is_shell:
            cmd_obj.module(connection, target, subcmd, log)
            return
        cmd = cmd_obj.path
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
    global REPORTED_IN
    do_action = False
    permitted = False
    with lock:
        if not REPORTED_IN:
            connection.privmsg(CONTEXT.hostname, "online")
            REPORTED_IN = True
        if event.target in [CONTEXT.hostname] + CONTEXT.rooms:
            do_action = True
            for source in CONTEXT.permitted:
                if source in event.source:
                    permitted = True
                    break
    if do_action and event.type == "pubmsg":
        log.debug(event)
        with lock:
            for item in CONTEXT.commands:
                cmd_obj = CONTEXT.commands[item]
                if not cmd_obj.is_shell:
                    cmd_obj.handle(connection, event, log)
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
                            raise SMIRCError("bind reset")
                        except Empty:
                            pass
                    else:
                        raise SMIRCError(str(z))
        except Exception as e:
            log.warning("zmq error")
            log.warning(e)
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


def run(config=None,
        public=None,
        private=None,
        to=None,
        bot=None,
        arguments=None):
    """Run smirc command(s)."""
    args = []
    inputs = {}
    inputs[_CONFIG_FLAG] = config
    inputs[_PRIVATE_FLAG] = private
    inputs[_PUBLIC_FLAG] = public
    inputs[_TO_FLAG] = to
    inputs[_BOT_FLAG] = bot
    for k in inputs:
        val = inputs[k]
        if val is not None:
            args.append(k)
            args.append(val)
    if arguments is not None:
        for a in arguments:
            args.append(a)
    _run(args, False)


class SMIRCError(Exception):
    """General smirc error."""


def _handle_app(is_app, message, code):
    """Handle application errors."""
    if is_app:
        print(message)
        exit(code)
    else:
        if code == 0:
            return
        raise SMIRCError("{} -> {}".format(message, code))


def get_args(arguments=None, is_app=False):
    """Get the arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(_CONFIG_FLAG,
                        type=str,
                        default="/etc/epiphyte.d/smirc.json")
    parser.add_argument(_PUBLIC_FLAG, action="store_true")
    parser.add_argument(_PRIVATE_FLAG, action="store_true")
    parser.add_argument(_TO_FLAG, type=str)
    parser.add_argument(_BOT_FLAG,
                        action="store_true")
    args, unknown = parser.parse_known_args(args=arguments)
    do_public = True
    do_private = True
    log.info(VERS)
    if args.public or args.private or args.to is not None and len(args.to) > 0:
        do_public = args.public
        do_private = args.private
    if not os.path.exists(args.config):
        _handle_app(is_app, "no config file exists", 1)
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
    setattr(obj, "commands", commands)
    log.info(commands.keys())
    log.debug(commands)
    if obj.rooms is None or \
       len(obj.rooms) == 0 or \
       obj.joint not in obj.rooms:
        obj.rooms.append(obj.joint)
    return (obj, unknown)


class Command(object):
    """Command objects."""

    def __init__(self, is_shell, path):
        """Init a command instance."""
        self.is_shell = is_shell
        self.path = path
        self._mod = None
        self._is_handle = False
        self._is_execute = False
        if not self.is_shell:
            self._mod = self._load_mod()
            avail = [x for x in dir(self._mod) if not x.startswith("_")]
            self._is_handle = "handle" in avail
            self._is_execute = "execute" in avail
            if not self._is_handle and not self._is_execute:
                log.warn("module handler has not actions")

    def _load_mod(self):
        """Module loading/import for commands."""
        spec = importlib.util.spec_from_file_location("smirc.mod", self.path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Module()

    def handle(self, connection, event, log):
        """Handle a message entirely."""
        if self._is_handle:
            self._mod.handle(connection, event, log)

    def module(self, connection, target, subcmds, log):
        """Execute command module."""
        if self._is_execute:
            self._mod.execute(connection, target, subcmds, log)


def load_config_context(obj, file_name, commands):
    """Load a config context into the object."""
    with open(file_name) as f:
        cfg = json.loads(f.read())
        for k in cfg.keys():
            if k in [_CMD_TYPE, _MOD_TYPE]:
                sub = cfg[k]
                for sub_key in sub.keys():
                    use_key = IND + sub_key
                    if use_key in commands:
                        log.warn("overwriting defined command: " + use_key)
                    commands[use_key] = Command(k == _CMD_TYPE,
                                                sub[sub_key])
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
        log.warning(z)
    return result


def on_pong(connection, event):
    """PONG received."""
    log.debug(event)
    global LAST_PONG
    with lock:
        LAST_PONG = 0


def main():
    """Program entry."""
    _run(None, True)


def _run(args, is_app):
    """Execute the program/run the program."""
    global CONTEXT
    global READY
    global RESET
    global LAST_PONG
    global RETRIES
    global KILLED
    parsed = get_args(arguments=args, is_app=is_app)
    args = parsed[0]
    with lock:
        CONTEXT = args
    if not args.bot:
        log.info("client")
        code = 0
        if not sending(args, parsed[1]):
            code = 1
        return _handle_app(is_app, "client executed", code)
    if args.server == "example.com":
        _handle_app(is_app, "default/example server detected...exiting...", 1)
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
                        _handle_app(is_app, "kill kill kill", 1)
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
                        raise SMIRCError("resetting...")
                    if LAST_PONG > 10:
                        LAST_PONG = 0
                        raise SMIRCError("no recent pongs...")
                time.sleep(args.poll)
                do_ping += 1
                if do_ping > 10:
                    do_ping = 0
                    c.ping(args.hostname)
                    with lock:
                        LAST_PONG += 1
        except Exception as e:
            log.warning(e)
            log.warning("will retry shortly")
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
