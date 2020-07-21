

class Authentication:
    """Manage authentication tokens for Chromoting/xmpp"""

    def __init__(self):
        # Note: Initial values are never used.
        self.login = None
        self.oauth_refresh_token = None

    def copy_from(self, config):
        """Loads the config and returns false if the config is invalid."""
        try:
            self.login = config["xmpp_login"]
            self.oauth_refresh_token = config["oauth_refresh_token"]
        except KeyError:
            return False
        return True

    def copy_to(self, config):
        config["xmpp_login"] = self.login
        config["oauth_refresh_token"] = self.oauth_refresh_token
