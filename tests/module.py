"""Test module/example."""


class Module(object):
    """Loadable module."""

    def handle(self, connection, event, log):
        """Handle events."""
        log.info('handle')

    def execute(self, connection, target, subcmds, log):
        """Execute the module."""
        log.info("module")
