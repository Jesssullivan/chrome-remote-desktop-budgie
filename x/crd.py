#!/usr/bin/python3
"""
Forceful server controls for chrome remote desktop.
Written by Jess Sullivan
@ https://github.com/Jesssullivan/chrome-remote-desktop-budgie
@ https://transscendsurvival.org/
"""

from Remote import *

# This script is intended to run continuously as a background daemon
# process, running under an ordinary (non-root) user account.
# If this env var is defined, extra host params will be loaded from this env var
# as a list of strings separated by space (\s+). Note that param that contains
# space is currently NOT supported and will be broken down into two params at
# the space character.
HOST_EXTRA_PARAMS_ENV_VAR = "CHROME_REMOTE_DESKTOP_HOST_EXTRA_PARAMS"

# This script has a sensible default for the initial and maximum desktop size,
# which can be overridden either on the command-line, or via a comma-separated
# list of sizes in this environment variable.
DEFAULT_SIZES_ENV_VAR = "CHROME_REMOTE_DESKTOP_DEFAULT_DESKTOP_SIZES"

# By default, this script launches Xvfb as the virtual X display.
USE_XORG_ENV_VAR = "CHROME_REMOTE_DESKTOP_USE_XORG"

# The amount of video RAM the dummy driver should claim to have, which limits
# the maximum possible resolution.
# 1048576 KiB = 1 GiB, which is the amount of video RAM needed to have a
# 16384x16384 pixel frame buffer (the maximum size supported by VP8) with 32
# bits per pixel.
XORG_DUMMY_VIDEO_RAM = 1048576  # KiB

# By default, provide a maximum size that is large enough to support clients
# with large or multiple monitors. This is a comma-separated list of
# resolutions that will be made available if the X server supports RANDR. These
# defaults can be overridden in ~/.profile.
DEFAULT_SIZES = remote.remote_sizes()
DEFAULT_SIZES_XORG = remote.remote_sizes()

SCRIPT_PATH = os.path.abspath(sys.argv[0])
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)

if os.path.basename(sys.argv[0]) == 'linux_me2me_host.py':
    # Needed for swarming/isolate tests.
    HOST_BINARY_PATH = os.path.join(SCRIPT_DIR,
                                    "../../../out/Release/remoting_me2me_host")
else:
    HOST_BINARY_PATH = os.path.join(SCRIPT_DIR, "chrome-remote-desktop-host")

USER_SESSION_PATH = os.path.join(SCRIPT_DIR, "user-session")

CHROME_REMOTING_GROUP_NAME = "chrome-remote-desktop"

HOME_DIR = os.environ["HOME"]
CONFIG_DIR = os.path.join(HOME_DIR, ".config/chrome-remote-desktop")
SESSION_FILE_PATH = os.path.join(HOME_DIR, ".chrome-remote-desktop-session")
SYSTEM_SESSION_FILE_PATH = "/etc/chrome-remote-desktop-session"

DEBIAN_XSESSION_PATH = "/etc/X11/Xsession"

X_LOCK_FILE_TEMPLATE = "/tmp/.X%d-lock"
FIRST_X_DISPLAY_NUMBER = remote.get_display()

# Amount of time to wait between relaunching processes.
SHORT_BACKOFF_TIME = 5
LONG_BACKOFF_TIME = 60

# How long a process must run in order not to be counted against the restart
# thresholds.
MINIMUM_PROCESS_LIFETIME = 60

# Thresholds for switching from fast- to slow-restart and for giving up
# trying to restart entirely.
SHORT_BACKOFF_THRESHOLD = 5
MAX_LAUNCH_FAILURES = SHORT_BACKOFF_THRESHOLD + 10

# Number of seconds to save session output to the log.
SESSION_OUTPUT_TIME_LIMIT_SECONDS = 300

# Host offline reason if the X server retry count is exceeded.
HOST_OFFLINE_REASON_X_SERVER_RETRIES_EXCEEDED = "X_SERVER_RETRIES_EXCEEDED"

# Host offline reason if the X session retry count is exceeded.
HOST_OFFLINE_REASON_SESSION_RETRIES_EXCEEDED = "SESSION_RETRIES_EXCEEDED"

# Host offline reason if the host retry count is exceeded. (Note: It may or may
# not be possible to send this, depending on why the host is failing.)
HOST_OFFLINE_REASON_HOST_RETRIES_EXCEEDED = "HOST_RETRIES_EXCEEDED"

# This is the file descriptor used to pass messages to the user_session binary
# during startup. It must be kept in sync with kMessageFd in
# remoting_user_session.cc.
USER_SESSION_MESSAGE_FD = 202

# This is the exit code used to signal to wrapper that it should restart instead
# of exiting. It must be kept in sync with kRelaunchExitCode in
# remoting_user_session.cc.
RELAUNCH_EXIT_CODE = 41

# This exit code is returned when a needed binary such as user-session or sg
# cannot be found.
COMMAND_NOT_FOUND_EXIT_CODE = 127

# This exit code is returned when a needed binary exists but cannot be executed.
COMMAND_NOT_EXECUTABLE_EXIT_CODE = 126

# Globals needed by the atexit cleanup() handler.
g_desktop = None
g_host_hash = hashlib.md5(socket.gethostname().encode()).hexdigest()


def gen_xorg_config(sizes):
    return (
        # This causes X to load the default GLX module, even if a proprietary one
        # is installed in a different directory.
        'Section "Files"\n'
        '  ModulePath "/usr/lib/xorg/modules"\n'
        'EndSection\n'
        '\n'
        # Suppress device probing, which happens by default.
        'Section "ServerFlags"\n'
        '  Option "AutoAddDevices" "false"\n'
        '  Option "AutoEnableDevices" "false"\n'
        '  Option "DontVTSwitch" "true"\n'
        '  Option "PciForceNone" "true"\n'
        'EndSection\n'
        '\n'
        'Section "InputDevice"\n'
        # The host looks for this name to check whether it's running in a virtual
        # session
        '  Identifier "Chrome Remote Desktop Input"\n'
        # While the xorg.conf man page specifies that both of these options are
        # deprecated synonyms for `Option "Floating" "false"`, it turns out that
        # if both aren't specified, the Xorg server will automatically attempt to
        # add additional devices.
        '  Option "CoreKeyboard" "true"\n'
        '  Option "CorePointer" "true"\n'
        '  Driver "void"\n'
        'EndSection\n'
        '\n'
        'Section "Device"\n'
        '  Identifier "Chrome Remote Desktop Videocard"\n'
        '  Driver "dummy"\n'
        '  VideoRam {video_ram}\n'
        'EndSection\n'
        '\n'
        'Section "Monitor"\n'
        '  Identifier "Chrome Remote Desktop Monitor"\n'
        # The horizontal sync rate was calculated from the vertical refresh rate
        # and the modline template:
        # (33000 (vert total) * 0.1 Hz = 3.3 kHz)
        '  HorizSync   3.3\n'  # kHz
        # The vertical refresh rate was chosen both to be low enough to have an
        # acceptable dot clock at high resolutions, and then bumped down a little
        # more so that in the unlikely event that a low refresh rate would break
        # something, it would break obviously.
        '  VertRefresh 0.1\n'  # Hz
        '{modelines}'
        'EndSection\n'
        '\n'
        'Section "Screen"\n'
        '  Identifier "Chrome Remote Desktop Screen"\n'
        '  Device "Chrome Remote Desktop Videocard"\n'
        '  Monitor "Chrome Remote Desktop Monitor"\n'
        '  DefaultDepth 24\n'
        '  SubSection "Display"\n'
        '    Viewport 0 0\n'
        '    Depth 24\n'
        '    Modes {modes}\n'
        '  EndSubSection\n'
        'EndSection\n'
        '\n'
        'Section "ServerLayout"\n'
        '  Identifier   "Chrome Remote Desktop Layout"\n'
        '  Screen       "Chrome Remote Desktop Screen"\n'
        '  InputDevice  "Chrome Remote Desktop Input"\n'
        'EndSection\n'.format(
            # This Modeline template allows resolutions up to the dummy driver's
            # max supported resolution of 32767x32767 without additional
            # calculation while meeting the driver's dot clock requirements. Note
            # that VP8 (and thus the amount of video RAM chosen) only support a
            # maximum resolution of 16384x16384.
            # 32767x32767 should be possible if we switch fully to VP9 and
            # increase the video RAM to 4GiB.
            # The dot clock was calculated to match the VirtRefresh chosen above.
            # (33000 * 33000 * 0.1 Hz = 108.9 MHz)
            # Changes this line require matching changes to HorizSync and
            # VertRefresh.
            modelines="".join(
                '  Modeline "{0}x{1}" 108.9 {0} 32998 32999 33000 '
                '{1} 32998 32999 33000\n'.format(w, h) for w, h in sizes),
            modes=" ".join('"{0}x{1}"'.format(w, h) for w, h in sizes),
            video_ram=XORG_DUMMY_VIDEO_RAM))


def display_manager_is_gdm():
    try:
        # Open as binary to avoid any encoding errors
        with open('/etc/X11/default-display-manager', 'rb') as file:
            if file.read().strip() in [b'/usr/sbin/gdm', b'/usr/sbin/gdm3']:
                return True
        # Fall through to process checking even if the file doesn't contain gdm.
    except:
        # If we can't read the file, move on to checking the process list.
        pass

    for process in psutil.process_iter():
        if process.name() in ['gdm', 'gdm3']:
            return True

    return False


def is_supported_platform():
    # Always assume that the system is supported if the config directory or
    # session file exist.
    if (os.path.isdir(CONFIG_DIR) or os.path.isfile(SESSION_FILE_PATH) or
            os.path.isfile(SYSTEM_SESSION_FILE_PATH)):
        return True

    # There's a bug in recent versions of GDM that will prevent a user from
    # logging in via GDM when there is already an x11 session running for that
    # user (such as the one started by CRD). Since breaking local login is a
    # pretty serious issue, we want to disallow host set up through the website.
    # Unfortunately, there's no way to return a specific error to the website, so
    # we just return False to indicate an unsupported platform. The user can still
    # set up the host using the headless setup flow, where we can at least display
    # a warning. See https://gitlab.gnome.org/GNOME/gdm/-/issues/580 for details
    # of the bug and fix.
    if display_manager_is_gdm():
        return False

    # The session chooser expects a Debian-style Xsession script.
    return os.path.isfile(DEBIAN_XSESSION_PATH)



def parse_config_arg(args):
    """Parses only the --config option from a given command-line.

  Returns:
    A two-tuple. The first element is the value of the --config option (or None
    if it is not specified), and the second is a list containing the remaining
    arguments
  """

    # By default, argparse will exit the program on error. We would like it not to
    # do that.
    class ArgumentParserError(Exception):
        pass

    class ThrowingArgumentParser(argparse.ArgumentParser):
        def error(self, message):
            raise ArgumentParserError(message)

    parser = ThrowingArgumentParser()
    parser.add_argument("--config", nargs='?', action="store")

    try:
        result = parser.parse_known_args(args)
        return (result[0].config, result[1])
    except ArgumentParserError:
        return (None, list(args))


def get_daemon_proc(config_file, require_child_process=False):
    """Checks if there is already an instance of this script running against
  |config_file|, and returns a psutil.Process instance for it. If
  |require_child_process| is true, only check for an instance with the
  --child-process flag specified.

  If a process is found without --config in the command line, get_daemon_proc
  will fall back to the old behavior of checking whether the script path matches
  the current script. This is to facilitate upgrades from previous versions.

  Returns:
    A Process instance for the existing daemon process, or None if the daemon
    is not running.
  """

    # Note: When making changes to how instances are detected, it is imperative
    # that this function retains the ability to find older versions. Otherwise,
    # upgrades can leave the user with two running sessions, with confusing
    # results.

    uid = os.getuid()
    this_pid = os.getpid()

    # This function should return the process with the --child-process flag if it
    # exists. If there's only a process without, it might be a legacy process.
    non_child_process = None

    # Support new & old psutil API. This is the right way to check, according to
    # http://grodola.blogspot.com/2014/01/psutil-20-porting.html
    if psutil.version_info >= (2, 0):
        psget = lambda x: x()
    else:
        psget = lambda x: x

    for process in psutil.process_iter():
        # Skip any processes that raise an exception, as processes may terminate
        # during iteration over the list.
        try:
            # Skip other users' processes.
            if psget(process.uids).real != uid:
                continue

            # Skip the process for this instance.
            if process.pid == this_pid:
                continue

            # |cmdline| will be [python-interpreter, script-file, other arguments...]
            cmdline = psget(process.cmdline)
            if len(cmdline) < 2:
                continue
            if (os.path.basename(cmdline[0]).startswith('python') and
                    os.path.basename(cmdline[1]) == os.path.basename(sys.argv[0]) and
                    "--start" in cmdline):
                process_config = parse_config_arg(cmdline[2:])[0]

                # Fall back to old behavior if there is no --config argument
                # TODO(rkjnsn): Consider removing this fallback once sufficient time
                # has passed.
                if process_config == config_file or (process_config is None and
                                                     cmdline[1] == sys.argv[0]):
                    if "--child-process" in cmdline:
                        return process
                    else:
                        non_child_process = process

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return non_child_process if not require_child_process else None


def choose_x_session():
    """Chooses the most appropriate X session command for this system.

  Returns:
    A string containing the command to run, or a list of strings containing
    the executable program and its arguments, which is suitable for passing as
    the first parameter of subprocess.Popen().  If a suitable session cannot
    be found, returns None.
  """
    XSESSION_FILES = [
        SESSION_FILE_PATH,
        SYSTEM_SESSION_FILE_PATH]
    for startup_file in XSESSION_FILES:
        startup_file = os.path.expanduser(startup_file)
        if os.path.exists(startup_file):
            if os.access(startup_file, os.X_OK):
                # "/bin/sh -c" is smart about how to execute the session script and
                # works in cases where plain exec() fails (for example, if the file is
                # marked executable, but is a plain script with no shebang line).
                return ["/bin/sh", "-c", pipes.quote(startup_file)]
            else:
                # If this is a system-wide session script, it should be run using the
                # system shell, ignoring any login shell that might be set for the
                # current user.
                return ["/bin/sh", startup_file]

    # If there's no configuration, show the user a session chooser.
    return [HOST_BINARY_PATH, "--type=xsession_chooser"]


def run_command_with_group(command, group):
    """Run a command with a different primary group."""

    # This is implemented using sg, which is an odd character and will try to
    # prompt for a password if it can't verify the user is a member of the given
    # group, along with in a few other corner cases. (It will prompt in the
    # non-member case even if the group doesn't have a password set.)
    #
    # To prevent sg from prompting the user for a password that doesn't exist,
    # redirect stdin and detach sg from the TTY. It will still print something
    # like "Password: crypt: Invalid argument", so redirect stdout and stderr, as
    # well. Finally, have the shell unredirect them when executing user-session.
    #
    # It is also desirable to have some way to tell whether any errors are
    # from sg or the command, which is done using a pipe.

    def pre_exec(read_fd, write_fd):
        os.close(read_fd)

        # /bin/sh may be dash, which only allows redirecting file descriptors 0-9,
        # the minimum required by POSIX. Since there may be files open elsewhere,
        # move the relevant file descriptors to specific numbers under that limit.
        # Because this runs in the child process, it doesn't matter if existing file
        # descriptors are closed in the process. After, stdio will be redirected to
        # /dev/null, write_fd will be moved to 6, and the old stdio will be moved
        # to 7, 8, and 9.
        if (write_fd != 6):
            os.dup2(write_fd, 6)
            os.close(write_fd)
        os.dup2(0, 7)
        os.dup2(1, 8)
        os.dup2(2, 9)
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)

        # os.setsid will detach subprocess from the TTY
        os.setsid()

    # Pipe to check whether sg successfully ran our command.
    read_fd, write_fd = os.pipe()
    try:
        # sg invokes the provided argument using /bin/sh. In that shell, first write
        # "success\n" to the pipe, which is checked later to determine whether sg
        # itself succeeded, and then restore stdio, close the extra file
        # descriptors, and exec the provided command.
        process = subprocess.Popen(
            ["sg", group,
             "echo success >&6; exec {command} "
             # Restore original stdio
             "0<&7 1>&8 2>&9 "
             # Close no-longer-needed file descriptors
             "6>&- 7<&- 8>&- 9>&-"
                 .format(command=" ".join(map(pipes.quote, command)))],
            # It'd be nice to use pass_fds instead close_fds=False. Unfortunately,
            # pass_fds doesn't seem usable with remapping. It runs after preexec_fn,
            # which does the remapping, but complains if the specified fds don't
            # exist ahead of time.
            close_fds=False, preexec_fn=lambda: pre_exec(read_fd, write_fd))
        result = process.wait()
    except OSError as e:
        logging.error("Failed to execute sg: {}".format(e.strerror))
        if e.errno == errno.ENOENT:
            result = COMMAND_NOT_FOUND_EXIT_CODE
        else:
            result = COMMAND_NOT_EXECUTABLE_EXIT_CODE
        # Skip pipe check, since sg was never executed.
        os.close(read_fd)
        return result
    except KeyboardInterrupt:
        # Because sg is in its own session, it won't have gotten the interrupt.
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
            result = process.wait()
        except OSError:
            logging.warning("Command may still be running")
            result = 1
    finally:
        os.close(write_fd)

    with os.fdopen(read_fd) as read_file:
        contents = read_file.read()
    if contents != "success\n":
        # No success message means sg didn't execute the command. (Maybe the user
        # is not a member of the group?)
        logging.error("Failed to access {} group. Is the user a member?"
                      .format(group))
        result = COMMAND_NOT_EXECUTABLE_EXIT_CODE

    return result


def start_via_user_session(foreground):
    # We need to invoke user-session
    command = [USER_SESSION_PATH, "start"]
    if foreground:
        command += ["--foreground"]
    command += ["--"] + sys.argv[1:]
    try:
        process = subprocess.Popen(command)
        result = process.wait()
    except OSError as e:
        if e.errno == errno.EACCES:
            # User may have just been added to the CRD group, in which case they
            # won't be able to execute user-session directly until they log out and
            # back in. In the mean time, we can try to switch to the CRD group and
            # execute user-session.
            result = run_command_with_group(command, CHROME_REMOTING_GROUP_NAME)
        else:
            logging.error("Could not execute {}: {}"
                          .format(USER_SESSION_PATH, e.strerror))
            if e.errno == errno.ENOENT:
                result = COMMAND_NOT_FOUND_EXIT_CODE
            else:
                result = COMMAND_NOT_EXECUTABLE_EXIT_CODE
    except KeyboardInterrupt:
        # Child will have also gotten the interrupt. Wait for it to exit.
        result = process.wait()

    return result


def cleanup():
    logging.info("Cleanup.")

    global g_desktop
    if g_desktop is not None:
        g_desktop.shutdown_all_procs()
        if g_desktop.xorg_conf is not None:
            os.remove(g_desktop.xorg_conf)

    g_desktop = None
    ParentProcessLogger.release_parent_if_connected(False)


def relaunch_self():
    """Relaunches the session to pick up any changes to the session logic in case
  Chrome Remote Desktop has been upgraded. We return a special exit code to
  inform user-session that it should relaunch.
  """

    # cleanup run via atexit
    sys.exit(RELAUNCH_EXIT_CODE)


def waitpid_with_timeout(pid, deadline):
    """Wrapper around os.waitpid() which waits until either a child process dies
  or the deadline elapses.

  Args:
    pid: Process ID to wait for, or -1 to wait for any child process.
    deadline: Waiting stops when time.time() exceeds this value.

  Returns:
    (pid, status): Same as for os.waitpid(), except that |pid| is 0 if no child
    changed state within the timeout.

  Raises:
    Same as for os.waitpid().
  """
    while time.time() < deadline:
        pid, status = os.waitpid(pid, os.WNOHANG)
        if pid != 0:
            return (pid, status)
        time.sleep(1)
    return (0, 0)


def waitpid_handle_exceptions(pid, deadline):
    """Wrapper around os.waitpid()/waitpid_with_timeout(), which waits until
  either a child process exits or the deadline elapses, and retries if certain
  exceptions occur.

  Args:
    pid: Process ID to wait for, or -1 to wait for any child process.
    deadline: If non-zero, waiting stops when time.time() exceeds this value.
      If zero, waiting stops when a child process exits.

  Returns:
    (pid, status): Same as for waitpid_with_timeout(). |pid| is non-zero if and
    only if a child exited during the wait.

  Raises:
    Same as for os.waitpid(), except:
      OSError with errno==EINTR causes the wait to be retried (this can happen,
      for example, if this parent process receives SIGHUP).
      OSError with errno==ECHILD means there are no child processes, and so
      this function sleeps until |deadline|. If |deadline| is zero, this is an
      error and the OSError exception is raised in this case.
  """
    while True:
        try:
            if deadline == 0:
                pid_result, status = os.waitpid(pid, 0)
            else:
                pid_result, status = waitpid_with_timeout(pid, deadline)
            return pid_result, status
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            elif e.errno == errno.ECHILD:
                now = time.time()
                if deadline == 0:
                    # No time-limit and no child processes. This is treated as an error
                    # (see docstring).
                    raise
                elif deadline > now:
                    time.sleep(deadline - now)
                return 0, 0
            else:
                # Anything else is an unexpected error.
                raise


def watch_for_resolution_changes(initial_size):
    """Watches for any resolution-changes which set the maximum screen resolution,
  and resets the initial size if this happens.

  The Ubuntu desktop has a component (the 'xrandr' plugin of
  unity-settings-daemon) which often changes the screen resolution to the
  first listed mode. This is the built-in mode for the maximum screen size,
  which can trigger excessive CPU usage in some situations. So this is a hack
  which waits for any such events, and undoes the change if it occurs.

  Sometimes, the user might legitimately want to use the maximum available
  resolution, so this monitoring is limited to a short time-period.
  """
    for _ in range(30):
        time.sleep(1)

        xrandr_output = subprocess.Popen(["xrandr"],
                                         stdout=subprocess.PIPE).communicate()[0]
        matches = re.search(br'current (\d+) x (\d+), maximum (\d+) x (\d+)',
                            xrandr_output)

        # No need to handle ValueError. If xrandr fails to give valid output,
        # there's no point in continuing to monitor.
        current_size = (int(matches.group(1)), int(matches.group(2)))
        maximum_size = (int(matches.group(3)), int(matches.group(4)))

        if current_size != initial_size:
            # Resolution change detected.
            if current_size == maximum_size:
                # This was probably an automated change from unity-settings-daemon, so
                # undo it.
                label = "%dx%d" % initial_size
                args = ["xrandr", "-s", label]
                subprocess.call(args)
                args = ["xrandr", "--dpi", "96"]
                subprocess.call(args)

            # Stop monitoring after any change was detected.
            break


def main():
    EPILOG = """This script is not intended for use by end-users.  To configure
Chrome Remote Desktop, please install the app from the Chrome
Web Store: https://chrome.google.com/remotedesktop"""
    parser = argparse.ArgumentParser(
        usage="Usage: %(prog)s [options] [ -- [ X server options ] ]",
        epilog=EPILOG)
    parser.add_argument("-s", "--size", dest="size", action="append",
                        help="Dimensions of virtual desktop. This can be "
                             "specified multiple times to make multiple screen "
                             "resolutions available (if the X server supports this).")
    parser.add_argument("-f", "--foreground", dest="foreground", default=False,
                        action="store_true",
                        help="Don't run as a background daemon.")
    parser.add_argument("--start", dest="start", default=False,
                        action="store_true",
                        help="Start the host.")
    parser.add_argument("-k", "--stop", dest="stop", default=False,
                        action="store_true",
                        help="Stop the daemon currently running.")
    parser.add_argument("--get-status", dest="get_status", default=False,
                        action="store_true",
                        help="Prints host status")
    parser.add_argument("--check-running", dest="check_running",
                        default=False, action="store_true",
                        help="Return 0 if the daemon is running, or 1 otherwise.")
    parser.add_argument("--config", dest="config", action="store",
                        help="Use the specified configuration file.")
    parser.add_argument("--reload", dest="reload", default=False,
                        action="store_true",
                        help="Signal currently running host to reload the "
                             "config.")
    parser.add_argument("--add-user", dest="add_user", default=False,
                        action="store_true",
                        help="Add current user to the chrome-remote-desktop "
                             "group.")
    parser.add_argument("--add-user-as-root", dest="add_user_as_root",
                        action="store", metavar="USER",
                        help="Adds the specified user to the "
                             "chrome-remote-desktop group (must be run as root).")
    # The script is being run as a child process under the user-session binary.
    # Don't daemonize and use the inherited environment.
    parser.add_argument("--child-process", dest="child_process", default=False,
                        action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--watch-resolution", dest="watch_resolution",
                        type=int, nargs=2, default=False, action="store",
                        help=argparse.SUPPRESS)
    parser.add_argument(dest="args", nargs="*", help=argparse.SUPPRESS)
    options = parser.parse_args()

    # Determine the filename of the host configuration.
    if options.config:
        config_file = options.config
    else:
        config_file = os.path.join(CONFIG_DIR, "host#%s.json" % g_host_hash)
    config_file = os.path.realpath(config_file)

    # Check for a modal command-line option (start, stop, etc.)
    if options.get_status:
        proc = get_daemon_proc(config_file)
        if proc is not None:
            print("STARTED")
        elif is_supported_platform():
            print("STOPPED")
        else:
            print("NOT_IMPLEMENTED")
        return 0

    if options.check_running:
        proc = get_daemon_proc(config_file)
        return 1 if proc is None else 0

    if options.stop:
        proc = get_daemon_proc(config_file)
        if proc is None:
            print("The daemon is not currently running")
        else:
            print("Killing process %s" % proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except psutil.TimeoutExpired:
                print("Timed out trying to kill daemon process")
                return 1
        return 0

    if options.reload:
        proc = get_daemon_proc(config_file)
        if proc is None:
            return 1
        proc.send_signal(signal.SIGHUP)
        return 0

    if options.add_user:
        user = getpass.getuser()

        try:
            if user in grp.getgrnam(CHROME_REMOTING_GROUP_NAME).gr_mem:
                logging.info("User '%s' is already a member of '%s'." %
                             (user, CHROME_REMOTING_GROUP_NAME))
                return 0
        except KeyError:
            logging.info("Group '%s' not found." % CHROME_REMOTING_GROUP_NAME)

        command = [SCRIPT_PATH, '--add-user-as-root', user]
        if os.getenv("DISPLAY"):
            # TODO(rickyz): Add a Polkit policy that includes a more friendly message
            # about what this command does.
            command = ["/usr/bin/pkexec"] + command
        else:
            command = ["/usr/bin/sudo", "-k", "--"] + command

        # Run with an empty environment out of paranoia, though if an attacker
        # controls the environment this script is run under, we're already screwed
        # anyway.
        os.execve(command[0], command, {})
        return 1

    if options.add_user_as_root is not None:
        if os.getuid() != 0:
            logging.error("--add-user-as-root can only be specified as root.")
            return 1

        user = options.add_user_as_root
        try:
            pwd.getpwnam(user)
        except KeyError:
            logging.error("user '%s' does not exist." % user)
            return 1

        try:
            subprocess.check_call(["/usr/sbin/groupadd", "-f",
                                   CHROME_REMOTING_GROUP_NAME])
            subprocess.check_call(["/usr/bin/gpasswd", "--add", user,
                                   CHROME_REMOTING_GROUP_NAME])
        except (ValueError, OSError, subprocess.CalledProcessError) as e:
            logging.error("Command failed: " + str(e))
            return 1

        return 0

    if options.watch_resolution:
        watch_for_resolution_changes(tuple(options.watch_resolution))
        return 0

    if not options.start:
        # If no modal command-line options specified, print an error and exit.
        print(EPILOG, file=sys.stderr)
        return 1

    # Determine whether a desktop is already active for the specified host
    # configuration.
    if get_daemon_proc(config_file, options.child_process) is not None:
        # Debian policy requires that services should "start" cleanly and return 0
        # if they are already running.
        if options.child_process:
            # If the script is running under user-session, try to relay the message.
            ParentProcessLogger.try_start_logging(USER_SESSION_MESSAGE_FD)
        logging.info("Service already running.")
        ParentProcessLogger.release_parent_if_connected(True)
        return 0

    if config_file != options.config:
        # --config was either not specified or isn't a canonical absolute path.
        # Replace it with the canonical path so get_daemon_proc can find us.
        sys.argv = ([sys.argv[0], "--config=" + config_file] +
                    parse_config_arg(sys.argv[1:])[1])
        if options.child_process:
            os.execvp(sys.argv[0], sys.argv)

    if not options.child_process:
        return start_via_user_session(options.foreground)

    # Start logging to user-session messaging pipe if it exists.
    ParentProcessLogger.try_start_logging(USER_SESSION_MESSAGE_FD)

    if display_manager_is_gdm():
        # See https://gitlab.gnome.org/GNOME/gdm/-/issues/580 for details on the
        # bug.
        gdm_message = (
            "WARNING: This system uses GDM. Some GDM versions have a bug that "
            "prevents local login while Chrome Remote Desktop is running. If you "
            "run into this issue, you can stop Chrome Remote Desktop by visiting "
            "https://remotedesktop.google.com/access on another machine and "
            "clicking the delete icon next to this machine. It may take up to five "
            "minutes for the Chrome Remote Desktop to exit on this machine and for "
            "local login to start working again.")
        logging.warning(gdm_message)
        # Also log to syslog so the user has a higher change of discovering the
        # message if they go searching.
        syslog.syslog(syslog.LOG_WARNING | syslog.LOG_DAEMON, gdm_message)

    if USE_XORG_ENV_VAR in os.environ:
        default_sizes = DEFAULT_SIZES_XORG
    else:
        default_sizes = DEFAULT_SIZES

    # Collate the list of sizes that XRANDR should support.
    if not options.size:
        if DEFAULT_SIZES_ENV_VAR in os.environ:
            default_sizes = os.environ[DEFAULT_SIZES_ENV_VAR]
        options.size = default_sizes.split(",")

    sizes = []
    for size in options.size:
        size_components = size.split("x")
        if len(size_components) != 2:
            parser.error("Incorrect size format '%s', should be WIDTHxHEIGHT" % size)

        try:
            width = int(size_components[0])
            height = int(size_components[1])

            # Enforce minimum desktop size, as a sanity-check.  The limit of 100 will
            # detect typos of 2 instead of 3 digits.
            if width < 100 or height < 100:
                raise ValueError
        except ValueError:
            parser.error("Width and height should be 100 pixels or greater")

        sizes.append((width, height))

    # Register an exit handler to clean up session process and the PID file.
    atexit.register(cleanup)

    # Load the initial host configuration.
    host_config = Config(config_file)
    try:
        host_config.load()
    except (IOError, ValueError) as e:
        print("Failed to load config: " + str(e), file=sys.stderr)
        return 1

    # Register handler to re-load the configuration in response to signals.
    for s in [signal.SIGHUP, signal.SIGINT, signal.SIGTERM]:
        signal.signal(s, SignalHandler(host_config))

    # Verify that the initial host configuration has the necessary fields.
    auth = Authentication()
    auth_config_valid = auth.copy_from(host_config)
    host = Host()
    host_config_valid = host.copy_from(host_config)
    if not host_config_valid or not auth_config_valid:
        logging.error("Failed to load host configuration.")
        return 1

    if host.host_id:
        logging.info("Using host_id: " + host.host_id)

    desktop = Desktop(sizes)

    # Keep track of the number of consecutive failures of any child process to
    # run for longer than a set period of time. The script will exit after a
    # threshold is exceeded.
    # There is no point in tracking the X session process separately, since it is
    # launched at (roughly) the same time as the X server, and the termination of
    # one of these triggers the termination of the other.
    x_server_inhibitor = RelaunchInhibitor("X server")
    session_inhibitor = RelaunchInhibitor("session")
    host_inhibitor = RelaunchInhibitor("host")
    all_inhibitors = [
        (x_server_inhibitor, HOST_OFFLINE_REASON_X_SERVER_RETRIES_EXCEEDED),
        (session_inhibitor, HOST_OFFLINE_REASON_SESSION_RETRIES_EXCEEDED),
        (host_inhibitor, HOST_OFFLINE_REASON_HOST_RETRIES_EXCEEDED)
    ]

    # Whether we are tearing down because the X server and/or session exited.
    # This keeps us from counting processes exiting because we've terminated them
    # as errors.
    tear_down = False

    while True:
        # If the session process or X server stops running (e.g. because the user
        # logged out), terminate all processes. The session will be restarted once
        # everything has exited.
        if tear_down:
            desktop.shutdown_all_procs()

            failure_count = 0
            for inhibitor, _ in all_inhibitors:
                if inhibitor.running:
                    inhibitor.record_stopped(True)
                failure_count += inhibitor.failures

            tear_down = False

            if failure_count == 0:
                # Since the user's desktop is already gone at this point, there's no
                # state to lose and now is a good time to pick up any updates to this
                # script that might have been installed.
                logging.info("Relaunching self")
                relaunch_self()
            else:
                # If there is a non-zero |failures| count, restarting the whole script
                # would lose this information, so just launch the session as normal,
                # below.
                pass

        relaunch_times = []

        # Set the backoff interval and exit if a process failed too many times.
        backoff_time = SHORT_BACKOFF_TIME
        for inhibitor, offline_reason in all_inhibitors:
            if inhibitor.failures >= MAX_LAUNCH_FAILURES:
                logging.error("Too many launch failures of '%s', exiting."
                              % inhibitor.label)
                desktop.report_offline_reason(host_config, offline_reason)
                return 1
            elif inhibitor.failures >= SHORT_BACKOFF_THRESHOLD:
                backoff_time = LONG_BACKOFF_TIME

            if inhibitor.is_inhibited():
                relaunch_times.append(inhibitor.earliest_relaunch_time)

        if relaunch_times:
            # We want to wait until everything is ready to start so we don't end up
            # launching things in the wrong order due to differing relaunch times.
            logging.info("Waiting before relaunching")
        else:
            if desktop.x_proc is None and desktop.session_proc is None:
                logging.info("Launching X server and X session.")
                desktop.launch_session(options.args)
                x_server_inhibitor.record_started(MINIMUM_PROCESS_LIFETIME,
                                                  backoff_time)
                session_inhibitor.record_started(MINIMUM_PROCESS_LIFETIME,
                                                 backoff_time)
            if desktop.host_proc is None:
                logging.info("Launching host process")

                extra_start_host_args = []
                if HOST_EXTRA_PARAMS_ENV_VAR in os.environ:
                    extra_start_host_args = \
                        re.split('\s+', os.environ[HOST_EXTRA_PARAMS_ENV_VAR].strip())
                desktop.launch_host(host_config, extra_start_host_args)

                host_inhibitor.record_started(MINIMUM_PROCESS_LIFETIME, backoff_time)

        deadline = max(relaunch_times) if relaunch_times else 0
        pid, status = waitpid_handle_exceptions(-1, deadline)
        if pid == 0:
            continue

        logging.info("wait() returned (%s,%s)" % (pid, status))

        # When a process has terminated, and we've reaped its exit-code, any Popen
        # instance for that process is no longer valid. Reset any affected instance
        # to None.
        if desktop.x_proc is not None and pid == desktop.x_proc.pid:
            logging.info("X server process terminated")
            desktop.x_proc = None
            x_server_inhibitor.record_stopped(False)
            tear_down = True

        if desktop.session_proc is not None and pid == desktop.session_proc.pid:
            logging.info("Session process terminated")
            desktop.session_proc = None
            # The session may have exited on its own or been brought down by the X
            # server dying. Check if the X server is still running so we know whom
            # to penalize.
            if desktop.check_x_responding():
                session_inhibitor.record_stopped(False)
            else:
                x_server_inhibitor.record_stopped(False)
            # Either way, we want to tear down the session.
            tear_down = True

        if desktop.host_proc is not None and pid == desktop.host_proc.pid:
            logging.info("Host process terminated")
            desktop.host_proc = None
            desktop.host_ready = False

            # These exit-codes must match the ones used by the host.
            # See remoting/host/host_exit_codes.h.
            # Delete the host or auth configuration depending on the returned error
            # code, so the next time this script is run, a new configuration
            # will be created and registered.
            if os.WIFEXITED(status):
                if os.WEXITSTATUS(status) == 100:
                    logging.info("Host configuration is invalid - exiting.")
                    return 0
                elif os.WEXITSTATUS(status) == 101:
                    logging.info("Host ID has been deleted - exiting.")
                    host_config.clear()
                    host_config.save_and_log_errors()
                    return 0
                elif os.WEXITSTATUS(status) == 102:
                    logging.info("OAuth credentials are invalid - exiting.")
                    return 0
                elif os.WEXITSTATUS(status) == 103:
                    logging.info("Host domain is blocked by policy - exiting.")
                    return 0
                # Nothing to do for Mac-only status 104 (login screen unsupported)
                elif os.WEXITSTATUS(status) == 105:
                    logging.info("Username is blocked by policy - exiting.")
                    return 0
                elif os.WEXITSTATUS(status) == 106:
                    logging.info("Host has been deleted - exiting.")
                    return 0
                else:
                    logging.info("Host exited with status %s." % os.WEXITSTATUS(status))
            elif os.WIFSIGNALED(status):
                logging.info("Host terminated by signal %s." % os.WTERMSIG(status))

            # The host may have exited on it's own or been brought down by the X
            # server dying. Check if the X server is still running so we know whom to
            # penalize.
            if desktop.check_x_responding():
                host_inhibitor.record_stopped(False)
            else:
                x_server_inhibitor.record_stopped(False)
                # Only tear down if the X server isn't responding.
                tear_down = True


