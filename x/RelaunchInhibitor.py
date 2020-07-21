from Remote import *


class RelaunchInhibitor:
    """Helper class for inhibiting launch of a child process before a timeout has
  elapsed.

  A managed process can be in one of these states:
    running, not inhibited (running == True)
    stopped and inhibited (running == False and is_inhibited() == True)
    stopped but not inhibited (running == False and is_inhibited() == False)

  Attributes:
    label: Name of the tracked process. Only used for logging.
    running: Whether the process is currently running.
    earliest_relaunch_time: Time before which the process should not be
      relaunched, or 0 if there is no limit.
    failures: The number of times that the process ran for less than a
      specified timeout, and had to be inhibited.  This count is reset to 0
      whenever the process has run for longer than the timeout.
  """

    def __init__(self, label):
        self.label = label
        self.running = False
        self.earliest_relaunch_time = 0
        self.earliest_successful_termination = 0
        self.failures = 0

    def is_inhibited(self):
        return (not self.running) and (time.time() < self.earliest_relaunch_time)

    def record_started(self, minimum_lifetime, relaunch_delay):
        """Record that the process was launched, and set the inhibit time to
    |timeout| seconds in the future."""
        self.earliest_relaunch_time = time.time() + relaunch_delay
        self.earliest_successful_termination = time.time() + minimum_lifetime
        self.running = True

    def record_stopped(self, expected):
        """Record that the process was stopped, and adjust the failure count
    depending on whether the process ran long enough. If the process was
    intentionally stopped (expected is True), the failure count will not be
    incremented."""
        self.running = False
        if time.time() >= self.earliest_successful_termination:
            self.failures = 0
        elif not expected:
            self.failures += 1
        logging.info("Failure count for '%s' is now %d", self.label, self.failures)

