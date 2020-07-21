from Remote import *


class ParentProcessLogger(object):
    """Redirects logs to the parent process, until the host is ready or quits.

  This class creates a pipe to allow logging from the daemon process to be
  copied to the parent process. The daemon process adds a log-handler that
  directs logging output to the pipe. The parent process reads from this pipe
  and writes the content to stderr. When the pipe is no longer needed (for
  example, the host signals successful launch or permanent failure), the daemon
  removes the log-handler and closes the pipe, causing the the parent process
  to reach end-of-file while reading the pipe and exit.

  The file descriptor for the pipe to the parent process should be passed to
  the constructor. The (grand-)child process should call start_logging() when
  it starts, and then use logging.* to issue log statements, as usual. When the
  child has either succesfully started the host or terminated, it must call
  release_parent() to allow the parent to exit.
  """

    __instance = None

    def __init__(self, write_fd):
        """Constructor.

    Constructs the singleton instance of ParentProcessLogger. This should be
    called at most once.

    write_fd: The write end of the pipe created by the parent process. If
              write_fd is not a valid file descriptor, the constructor will
              throw either IOError or OSError.
    """
        # Ensure write_pipe is closed on exec, otherwise it will be kept open by
        # child processes (X, host), preventing the read pipe from EOF'ing.
        old_flags = fcntl.fcntl(write_fd, fcntl.F_GETFD)
        fcntl.fcntl(write_fd, fcntl.F_SETFD, old_flags | fcntl.FD_CLOEXEC)
        self._write_file = os.fdopen(write_fd, 'w')
        self._logging_handler = None
        ParentProcessLogger.__instance = self

    def _start_logging(self):
        """Installs a logging handler that sends log entries to a pipe, prefixed
    with the string 'MSG:'. This allows them to be distinguished by the parent
    process from commands sent over the same pipe.

    Must be called by the child process.
    """
        self._logging_handler = logging.StreamHandler(self._write_file)
        self._logging_handler.setFormatter(logging.Formatter(fmt='MSG:%(message)s'))
        logging.getLogger().addHandler(self._logging_handler)

    def _release_parent(self, success):
        """Uninstalls logging handler and closes the pipe, releasing the parent.

    Must be called by the child process.

    success: If true, write a "host ready" message to the parent process before
             closing the pipe.
    """
        if self._logging_handler:
            logging.getLogger().removeHandler(self._logging_handler)
            self._logging_handler = None
        if not self._write_file.closed:
            if success:
                try:
                    self._write_file.write("READY\n")
                    self._write_file.flush()
                except IOError:
                    # A "broken pipe" IOError can happen if the receiving process
                    # (remoting_user_session) has exited (probably due to timeout waiting
                    # for the host to start).
                    # Trapping the error here means the host can continue running.
                    logging.info("Caught IOError writing READY message.")
            try:
                self._write_file.close()
            except IOError:
                pass

    @staticmethod
    def try_start_logging(write_fd):
        """Attempt to initialize ParentProcessLogger and start forwarding log
    messages.

    Returns False if the file descriptor was invalid (safe to ignore).
    """
        try:
            ParentProcessLogger(USER_SESSION_MESSAGE_FD)._start_logging()
            return True
        except (IOError, OSError):
            # One of these will be thrown if the file descriptor is invalid, such as
            # if the the fd got closed by the login shell. In that case, just continue
            # without sending log messages.
            return False

    @staticmethod
    def release_parent_if_connected(success):
        """If ParentProcessLogger is active, stop logging and release the parent.

    success: If true, signal to the parent that the script was successful.
    """
        instance = ParentProcessLogger.__instance
        if instance is not None:
            ParentProcessLogger.__instance = None
            instance._release_parent(success)

