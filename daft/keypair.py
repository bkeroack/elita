from M2Crypto import BIO, RSA

import daft_exceptions
import util

__author__ = 'bkeroack'



class KeyPair:
    def __init__(self, private_key, public_key):
        self.private_key = BIO.MemoryBuffer(private_key)
        self.public_key = BIO.MemoryBuffer(public_key)

    def verify_public(self):
        rsa = RSA.load_pub_key_bio(self.public_key)
        util.debugLog(self, "public key loaded successfully")

    def verify_private(self):
        rsa = RSA.load_key_bio(self.private_key)
        util.debugLog(self, "private key loaded successfully")
