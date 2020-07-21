from Remote import *


class Config:
    def __init__(self, path):
        self.path = path
        self.data = {}
        self.changed = False

    def load(self):
        """Loads the config from file.

    Raises:
      IOError: Error reading data
      ValueError: Error parsing JSON
    """
        settings_file = open(self.path, 'r')
        self.data = json.load(settings_file)
        self.changed = False
        settings_file.close()

    def save(self):
        """Saves the config to file.

    Raises:
      IOError: Error writing data
      TypeError: Error serialising JSON
    """
        if not self.changed:
            return
        old_umask = os.umask(0o066)
        try:
            settings_file = open(self.path, 'w')
            settings_file.write(json.dumps(self.data, indent=2))
            settings_file.close()
            self.changed = False
        finally:
            os.umask(old_umask)

    def save_and_log_errors(self):
        """Calls self.save(), trapping and logging any errors."""
        try:
            self.save()
        except (IOError, TypeError) as e:
            logging.error("Failed to save config: " + str(e))

    def get(self, key):
        return self.data.get(key)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value
        self.changed = True

    def clear(self):
        self.data = {}
        self.changed = True
