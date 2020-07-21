
from __init__ import *

from Remote import *
from crd import SESSION_OUTPUT_TIME_LIMIT_SECONDS


class SessionOutputFilterThread(threading.Thread):
    """Reads session log from a pipe and logs the output for amount of time
  defined by SESSION_OUTPUT_TIME_LIMIT_SECONDS."""

    def __init__(self, stream):
        threading.Thread.__init__(self)
        self.stream = stream
        self.daemon = True

    def run(self):
        started_time = time.time()
        is_logging = True
        while True:
            try:
                line = self.stream.readline();
            except IOError as e:
                print("IOError when reading session output: ", e)
                return

            if line == b"":
                # EOF reached. Just stop the thread.
                return

            if not is_logging:
                continue

            if time.time() - started_time >= SESSION_OUTPUT_TIME_LIMIT_SECONDS:
                is_logging = False
                print("Suppressing rest of the session output.", flush=True)
            else:
                # Pass stream bytes through as is instead of decoding and encoding.
                sys.stdout.buffer.write(
                    "Session output: ".encode(sys.stdout.encoding) + line)
                sys.stdout.flush()

