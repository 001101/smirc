#!/usr/env/python
"""Mock IRC client."""
import logging
import os

log = logging.getLogger("mock")
log.addHandler(logging.FileHandler("mock.log"))
log.setLevel(logging.INFO)


class Reactor(object):
    """Reactor object (mock)."""

    def __init__(self):
        """Init the instance."""
        self._s = Server()

    def server(self):
        """Get a mock server."""
        return self._s

    def process_once(self, timeout=None):
        """Process mock instance."""
        self._s._process()


class Connection(object):
    """Mock connection."""

    def __init__(self):
        """Init the instance."""
        pass

    def join(self, channel):
        """Join a channel."""
        log.info(channel)

    def privmsg(self, target, datum):
        """Send a private message."""
        log.info(target)
        log.info(datum)


class Event(object):
    """Mock event."""

    def __init__(self):
        """Init the mock event."""
        self.target = "#mock"
        self.arguments = []
        self.type = "pubmsg"


class Server(object):
    """Server object."""

    def __init__(self):
        """Init the mock server."""
        self._c = Client()
        self._idx = 0
        self._name = None

    def connect(self, server, port, name, password=None, connect_factory=None):
        """Mock connection."""
        self._name = "#" + name.replace("-bot", "")
        return self._c

    def _process(self):
        """Mock processing."""
        is_stop = self._idx > 5
        if is_stop:
            self._c.privmsg(self._name, "!killkillkill")
        self._idx += 1
        self._c._process()
        if is_stop:
            os.remove("running.tmp")


class Client(object):
    """Mock client."""

    def __init__(self):
        """Init the client."""
        self._handlers = []
        self._conn = Connection()
        self._evt = Event()

    def privmsg(self, targets, datum):
        """Send a private message."""
        self._conn.privmsg(targets, datum)
        evt = Event()
        evt.target = targets
        evt.arguments = datum.split(" ")
        self._send(evt)

    def add_global_handler(self, name, function):
        """Add a handler."""
        self._handlers.append(function)

    def ping(self, host):
        """Do a ping."""
        log.info("ping")
        log.info(host)

    def _process(self):
        """Process a request."""
        log.info('process')
        self._send(self._evt)

    def _send(self, evt):
        """Send data to handlers."""
        for item in self._handlers:
            item(self._conn, evt)
