

class Host:
    """This manages the configuration for a host."""

    def __init__(self):
        # Note: Initial values are never used.
        self.host_id = None
        self.host_name = None
        self.host_secret_hash = None
        self.private_key = None

    def copy_from(self, config):
        try:
            self.host_id = config.get("host_id")
            self.host_name = config["host_name"]
            self.host_secret_hash = config.get("host_secret_hash")
            self.private_key = config["private_key"]
        except KeyError:
            return False
        return bool(self.host_id)

    def copy_to(self, config):
        if self.host_id:
            config["host_id"] = self.host_id
        config["host_name"] = self.host_name
        config["host_secret_hash"] = self.host_secret_hash
        config["private_key"] = self.private_key
