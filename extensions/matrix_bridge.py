"""Matrix bridge for a listener."""


class MatrixBridgeModule(object):
    """Bridge implementation."""

    _url = "{}/_matrix/client/r0/rooms/{}/send/m.room.message?access_token={}"

    def __init(self):
        """Init definition."""
        self._post = None
        self._load_env()

    def _load_env(self):
        """Load environment."""
        room = None
        token = None
        url = None
        with open("/etc/epiphyte.d/environment", 'r') as f:
            for line in f:
                kv = line.split("=")
                if len(kv) == 2:
                    k = kv[0]
                    v = kv[1]
                    v = v[1:-1]
                    if k == "SYNAPSE_HOST":
                        url = v
                    elif k == "SYNAPSE_API_TOKEN":
                        token = v
                    elif k == "SYNAPSE_DEBUGGING":
                        room = v
        if room is not None and token is not None and url is not None:
            self._post = self._url.format(url, room, token)

    def handle(self, connection, event, log):
        """required method and signuatre for gliobal message handling."""
        try:
            if self._post is None:
                log.warn("no post settings enabled")
            data = event.arguments
            if data and len(data) > 0:
                for d in data:
                    obj = {}
                    obj["body"] = str(d)
                    obj["msgtype"] = "m.text"
                    req = urllib.request.Request(self._post)
                    req.add_header('Content-Type',
                                   'application/json; charset=utf-8')
                    urllib.request.urlopen(req,
                                           json.dumps(obj).encode("utf-8"))
        except Exception as e:
            log.error("matrix bridge error")
            log.error(str(e))