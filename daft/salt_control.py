import salt.client

__author__ = 'bkeroack'

class SaltController:
    def __init__(self, server_name):
        self.server_name = server_name
        self.salt_client = salt.client.LocalClient()

    def verify_connectivity(self, timeout=10):
        return len(self.salt_client.cmd(self.server_name, 'test.ping', timeout=timeout)) != 0

