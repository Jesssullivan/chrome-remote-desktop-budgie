from Remote import *
from crd import *


class Desktop:
    """Manage a single virtual desktop"""

    def __init__(self, sizes):
        self.x_proc = None
        self.session_proc = None
        self.host_proc = None
        self.child_env = None
        self.sizes = sizes
        self.xorg_conf = None
        self.pulseaudio_pipe = None
        self.server_supports_exact_resize = False
        self.server_supports_randr = False
        self.randr_add_sizes = False
        self.host_ready = False
        self.ssh_auth_sockname = None
        global g_desktop
        assert (g_desktop is None)
        g_desktop = self

    @staticmethod
    def get_unused_display_number(override=True):
        """Return a candidate display number for which there is currently no
    X Server lock file"""
        if not override:
            display = FIRST_X_DISPLAY_NUMBER
            while os.path.exists(X_LOCK_FILE_TEMPLATE % display):
              display += 1
            return display
        else:
            return FIRST_X_DISPLAY_NUMBER

    def _init_child_env(self):
        self.child_env = dict(os.environ)

        # Force GDK to use the X11 backend, as otherwise parts of the host that use
        # GTK can end up connecting to an active Wayland display instead of the
        # CRD X11 session.
        self.child_env["GDK_BACKEND"] = "x11"

        # Ensure that the software-rendering GL drivers are loaded by the desktop
        # session, instead of any hardware GL drivers installed on the system.
        library_path = (
                "/usr/lib/mesa-diverted/%(arch)s-linux-gnu:"
                "/usr/lib/%(arch)s-linux-gnu/mesa:"
                "/usr/lib/%(arch)s-linux-gnu/dri:"
                "/usr/lib/%(arch)s-linux-gnu/gallium-pipe" %
                {"arch": platform.machine()})

        if "LD_LIBRARY_PATH" in self.child_env:
            library_path += ":" + self.child_env["LD_LIBRARY_PATH"]

        self.child_env["LD_LIBRARY_PATH"] = library_path

    def _setup_pulseaudio(self):
        self.pulseaudio_pipe = None

        # pulseaudio uses UNIX sockets for communication. Length of UNIX socket
        # name is limited to 108 characters, so audio will not work properly if
        # the path is too long. To workaround this problem we use only first 10
        # symbols of the host hash.
        pulse_path = os.path.join(CONFIG_DIR,
                                  "pulseaudio#%s" % g_host_hash[0:10])
        if len(pulse_path) + len("/native") >= 108:
            logging.error("Audio will not be enabled because pulseaudio UNIX " +
                          "socket path is too long.")
            return False

        sink_name = "chrome_remote_desktop_session"
        pipe_name = os.path.join(pulse_path, "fifo_output")

        try:
            if not os.path.exists(pulse_path):
                os.mkdir(pulse_path)
        except IOError as e:
            logging.error("Failed to create pulseaudio pipe: " + str(e))
            return False

        try:
            pulse_config = open(os.path.join(pulse_path, "daemon.conf"), "w")
            pulse_config.write("default-sample-format = s16le\n")
            pulse_config.write("default-sample-rate = 48000\n")
            pulse_config.write("default-sample-channels = 2\n")
            pulse_config.close()

            pulse_script = open(os.path.join(pulse_path, "default.pa"), "w")
            pulse_script.write("load-module module-native-protocol-unix\n")
            pulse_script.write(
                ("load-module module-pipe-sink sink_name=%s file=\"%s\" " +
                 "rate=48000 channels=2 format=s16le\n") %
                (sink_name, pipe_name))
            pulse_script.close()
        except IOError as e:
            logging.error("Failed to write pulseaudio config: " + str(e))
            return False

        self.child_env["PULSE_CONFIG_PATH"] = pulse_path
        self.child_env["PULSE_RUNTIME_PATH"] = pulse_path
        self.child_env["PULSE_STATE_PATH"] = pulse_path
        self.child_env["PULSE_SINK"] = sink_name
        self.pulseaudio_pipe = pipe_name

        return True

    def _setup_gnubby(self):
        self.ssh_auth_sockname = ("/tmp/chromoting.%s.ssh_auth_sock" %
                                  os.environ["USER"])

    # Returns child environment not containing TMPDIR.
    # Certain values of TMPDIR can break the X server (crbug.com/672684), so we
    # want to make sure it isn't set in the envirionment we use to start the
    # server.
    def _x_env(self):
        if "TMPDIR" not in self.child_env:
            return self.child_env
        else:
            env_copy = dict(self.child_env)
            del env_copy["TMPDIR"]
            return env_copy

    def check_x_responding(self):
        """Checks if the X server is responding to connections."""
        with open(os.devnull, "r+") as devnull:
            exit_code = subprocess.call("xdpyinfo", env=self.child_env,
                                        stdout=devnull)
        return exit_code == 0

    def _wait_for_x(self):
        # Wait for X to be active.
        for _test in range(20):
            if self.check_x_responding():
                logging.info("X server is active.")
                return
            time.sleep(0.5)

        raise Exception("Could not connect to X server.")

    def _launch_xvfb(self, display, x_auth_file, extra_x_args):
        max_width = max([width for width, height in self.sizes])
        max_height = max([height for width, height in self.sizes])

        logging.info("Starting Xvfb on display :%d" % display)
        screen_option = "%dx%dx24" % (max_width, max_height)
        self.x_proc = subprocess.Popen(
            ["Xvfb", ":%d" % display,
             "-auth", x_auth_file,
             "-nolisten", "tcp",
             "-noreset",
             "-screen", "0", screen_option
             ] + extra_x_args, env=self._x_env())
        if not self.x_proc.pid:
            raise Exception("Could not start Xvfb.")

        self._wait_for_x()

        with open(os.devnull, "r+") as devnull:
            exit_code = subprocess.call("xrandr", env=self.child_env,
                                        stdout=devnull, stderr=devnull)
        if exit_code == 0:
            # RandR is supported
            self.server_supports_exact_resize = True
            self.server_supports_randr = True
            self.randr_add_sizes = True

    def _launch_xorg(self, display, x_auth_file, extra_x_args):
        with tempfile.NamedTemporaryFile(
                prefix="chrome_remote_desktop_",
                suffix=".conf", delete=False) as config_file:
            config_file.write(gen_xorg_config(self.sizes).encode())

        # We can't support exact resize with the current Xorg dummy driver.
        self.server_supports_exact_resize = False
        # But dummy does support RandR 1.0.
        self.server_supports_randr = True
        self.xorg_conf = config_file.name

        logging.info("Starting Xorg on display :%d" % display)
        # We use the child environment so the Xorg server picks up the Mesa libGL
        # instead of any proprietary versions that may be installed, thanks to
        # LD_LIBRARY_PATH.
        # Note: This prevents any environment variable the user has set from
        # affecting the Xorg server.
        self.x_proc = subprocess.Popen(
            ["Xorg", ":%d" % display,
             "-auth", x_auth_file,
             "-nolisten", "tcp",
             "-noreset",
             # Disable logging to a file and instead bump up the stderr verbosity
             # so the equivalent information gets logged in our main log file.
             "-logfile", "/dev/null",
             "-verbose", "3",
             "-config", config_file.name
             ] + extra_x_args, env=self._x_env())
        if not self.x_proc.pid:
            raise Exception("Could not start Xorg.")
        self._wait_for_x()

    def _launch_x_server(self, extra_x_args):
        x_auth_file = os.path.expanduser("~/.Xauthority")
        self.child_env["XAUTHORITY"] = x_auth_file
        display = self.get_unused_display_number()

        # Run "xauth add" with |child_env| so that it modifies the same XAUTHORITY
        # file which will be used for the X session.
        exit_code = subprocess.call("xauth add :%d . `mcookie`" % display,
                                    env=self.child_env, shell=True)
        if exit_code != 0:
            raise Exception("xauth failed with code %d" % exit_code)

        # Disable the Composite extension iff the X session is the default
        # Unity-2D, since it uses Metacity which fails to generate DAMAGE
        # notifications correctly. See crbug.com/166468.
        x_session = choose_x_session()
        if (len(x_session) == 2 and
                x_session[1] == "/usr/bin/gnome-session --session=ubuntu-2d"):
            extra_x_args.extend(["-extension", "Composite"])

        self.child_env["DISPLAY"] = ":%d" % display
        self.child_env["CHROME_REMOTE_DESKTOP_SESSION"] = "1"

        # Use a separate profile for any instances of Chrome that are started in
        # the virtual session. Chrome doesn't support sharing a profile between
        # multiple DISPLAYs, but Chrome Sync allows for a reasonable compromise.
        #
        # M61 introduced CHROME_CONFIG_HOME, which allows specifying a different
        # config base path while still using different user data directories for
        # different channels (Stable, Beta, Dev). For existing users who only have
        # chrome-profile, continue using CHROME_USER_DATA_DIR so they don't have to
        # set up their profile again.
        chrome_profile = os.path.join(CONFIG_DIR, "chrome-profile")
        chrome_config_home = os.path.join(CONFIG_DIR, "chrome-config")
        if (os.path.exists(chrome_profile)
                and not os.path.exists(chrome_config_home)):
            self.child_env["CHROME_USER_DATA_DIR"] = chrome_profile
        else:
            self.child_env["CHROME_CONFIG_HOME"] = chrome_config_home

        # Set SSH_AUTH_SOCK to the file name to listen on.
        if self.ssh_auth_sockname:
            self.child_env["SSH_AUTH_SOCK"] = self.ssh_auth_sockname

        if USE_XORG_ENV_VAR in os.environ:
            self._launch_xorg(display, x_auth_file, extra_x_args)
        else:
            self._launch_xvfb(display, x_auth_file, extra_x_args)

        # The remoting host expects the server to use "evdev" keycodes, but Xvfb
        # starts configured to use the "base" ruleset, resulting in XKB configuring
        # for "xfree86" keycodes, and screwing up some keys. See crbug.com/119013.
        # Reconfigure the X server to use "evdev" keymap rules.  The X server must
        # be started with -noreset otherwise it'll reset as soon as the command
        # completes, since there are no other X clients running yet.
        exit_code = subprocess.call(["setxkbmap", "-rules", "evdev"],
                                    env=self.child_env)
        if exit_code != 0:
            logging.error("Failed to set XKB to 'evdev'")

        if not self.server_supports_randr:
            return

        with open(os.devnull, "r+") as devnull:
            # Register the screen sizes with RandR, if needed.  Errors here are
            # non-fatal; the X server will continue to run with the dimensions from
            # the "-screen" option.
            if self.randr_add_sizes:
                for width, height in self.sizes:
                    label = "%dx%d" % (width, height)
                    args = ["xrandr", "--newmode", label, "0", str(width), "0", "0", "0",
                            str(height), "0", "0", "0"]
                    subprocess.call(args, env=self.child_env, stdout=devnull,
                                    stderr=devnull)
                    args = ["xrandr", "--addmode", "screen", label]
                    subprocess.call(args, env=self.child_env, stdout=devnull,
                                    stderr=devnull)

            # Set the initial mode to the first size specified, otherwise the X server
            # would default to (max_width, max_height), which might not even be in the
            # list.
            initial_size = self.sizes[0]
            label = "%dx%d" % initial_size
            args = ["xrandr", "-s", label]
            subprocess.call(args, env=self.child_env, stdout=devnull, stderr=devnull)

            # Set the physical size of the display so that the initial mode is running
            # at approximately 96 DPI, since some desktops require the DPI to be set
            # to something realistic.
            args = ["xrandr", "--dpi", "96"]
            subprocess.call(args, env=self.child_env, stdout=devnull, stderr=devnull)

            # Monitor for any automatic resolution changes from the desktop
            # environment.
            args = [SCRIPT_PATH, "--watch-resolution", str(initial_size[0]),
                    str(initial_size[1])]

            # It is not necessary to wait() on the process here, as this script's main
            # loop will reap the exit-codes of all child processes.
            subprocess.Popen(args, env=self.child_env, stdout=devnull, stderr=devnull)

    def _launch_x_session(self):
        # Start desktop session.
        # The /dev/null input redirection is necessary to prevent the X session
        # reading from stdin.  If this code runs as a shell background job in a
        # terminal, any reading from stdin causes the job to be suspended.
        # Daemonization would solve this problem by separating the process from the
        # controlling terminal.
        xsession_command = choose_x_session()
        if xsession_command is None:
            raise Exception("Unable to choose suitable X session command.")

        logging.info("Launching X session: %s" % xsession_command)
        self.session_proc = subprocess.Popen(xsession_command,
                                             stdin=open(os.devnull, "r"),
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT,
                                             cwd=HOME_DIR,
                                             env=self.child_env)

        output_filter_thread = SessionOutputFilterThread(self.session_proc.stdout)
        output_filter_thread.start()

        if not self.session_proc.pid:
            raise Exception("Could not start X session")

    def launch_session(self, x_args, override=True):
        self._init_child_env()
        self._setup_pulseaudio()
        self._setup_gnubby()
        if not override:
            self._launch_x_server(x_args)
            self._launch_x_session()
        else:
            display = self.get_unused_display_number()
            self.child_env["DISPLAY"] = ":%d" % display

    def launch_host(self, host_config, extra_start_host_args):
        # Start remoting host
        args = [HOST_BINARY_PATH, "--host-config=-"]
        if self.pulseaudio_pipe:
            args.append("--audio-pipe-name=%s" % self.pulseaudio_pipe)
        if self.server_supports_exact_resize:
            args.append("--server-supports-exact-resize")
        if self.ssh_auth_sockname:
            args.append("--ssh-auth-sockname=%s" % self.ssh_auth_sockname)

        args.extend(extra_start_host_args)

        # Have the host process use SIGUSR1 to signal a successful start.
        def sigusr1_handler(signum, frame):
            _ = signum, frame
            logging.info("Host ready to receive connections.")
            self.host_ready = True
            ParentProcessLogger.release_parent_if_connected(True)

        signal.signal(signal.SIGUSR1, sigusr1_handler)
        args.append("--signal-parent")

        logging.info(args)
        self.host_proc = subprocess.Popen(args, env=self.child_env,
                                          stdin=subprocess.PIPE)
        if not self.host_proc.pid:
            raise Exception("Could not start Chrome Remote Desktop host")

        try:
            self.host_proc.stdin.write(json.dumps(host_config.data).encode('UTF-8'))
            self.host_proc.stdin.flush()
        except IOError as e:
            # This can occur in rare situations, for example, if the machine is
            # heavily loaded and the host process dies quickly (maybe if the X
            # connection failed), the host process might be gone before this code
            # writes to the host's stdin. Catch and log the exception, allowing
            # the process to be retried instead of exiting the script completely.
            logging.error("Failed writing to host's stdin: " + str(e))
        finally:
            self.host_proc.stdin.close()

    def shutdown_all_procs(self):
        """Send SIGTERM to all procs and wait for them to exit. Will fallback to
    SIGKILL if a process doesn't exit within 10 seconds.
    """
        global psutil_proc
        for proc, name in [(self.x_proc, "X server"),
                           (self.session_proc, "session"),
                           (self.host_proc, "host")]:
            if proc is not None:
                logging.info("Terminating " + name)
                try:
                    psutil_proc = psutil.Process(proc.pid)
                    psutil_proc.terminate()

                    # Use a short timeout, to avoid delaying service shutdown if the
                    # process refuses to die for some reason.
                    psutil_proc.wait(timeout=10)
                except psutil.TimeoutExpired:
                    logging.error("Timed out - sending SIGKILL")
                    psutil_proc.kill()
                except psutil.Error:
                    logging.error("Error terminating process")
        self.x_proc = None
        self.session_proc = None
        self.host_proc = None

    def report_offline_reason(self, host_config, reason):
        """Attempt to report the specified offline reason to the registry. This
    is best effort, and requires a valid host config.
    """
        logging.info("Attempting to report offline reason: " + reason)
        args = [HOST_BINARY_PATH, "--host-config=-",
                "--report-offline-reason=" + reason]
        proc = subprocess.Popen(args, env=self.child_env, stdin=subprocess.PIPE)
        proc.communicate(json.dumps(host_config.data).encode('UTF-8'))

