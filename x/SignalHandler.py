import signal
from Remote import *
from crd import g_desktop


class SignalHandler:
    """Reload the config file on SIGHUP. Since we pass the configuration to the
  host processes via stdin, they can't reload it, so terminate them. They will
  be relaunched automatically with the new config."""

    def __init__(self, host_config):
        self.host_config = host_config

    def __call__(self, signum, _stackframe):
        if signum == signal.SIGHUP:
            logging.info("SIGHUP caught, restarting host.")
            try:
                self.host_config.load()
            except (IOError, ValueError) as e:
                logging.error("Failed to load config: " + str(e))
            if g_desktop is not None and g_desktop.host_proc:
                g_desktop.host_proc.send_signal(signal.SIGTERM)
        else:
            # Exit cleanly so the atexit handler, cleanup(), gets called.
            raise SystemExit
