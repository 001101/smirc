"""Test module/example."""


class Module(object):
    """Loadable module."""

    def execute(self, connection, target, subcmds, log):
        """Execute the module."""
        log.info("module")
