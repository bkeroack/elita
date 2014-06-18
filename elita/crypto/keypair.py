#from M2Crypto import BIO, RSA
#import base64
import elita.util


__author__ = 'bkeroack'



class KeyPair:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, private_key, public_key):
        pass
        #self.private_key = BIO.MemoryBuffer(private_key)
        #self.public_key_pkcs1 = public_key
        #self.public_key_x501 = None

    # def der_length(self, length):
    #     if length < 128:
    #         return chr(length)
    #     prefix = 0x80
    #     result = ''
    #     while length > 0:
    #         result = chr(length & 0xff) + result
    #         length >>= 8
    #         prefix += 1
    #     return chr(prefix) + result
    #
    # def process_public_key(self):
    #     '''converts PKCS#1 public key as output by ssh-keygen to X.501'''
    #     pk = self.public_key_pkcs1.split('\n')
    #     pk = '\0' + base64.decodestring("".join(pk[1:-2]))
    #     pk = '\x30\x0d\x06\x09\x2a\x86\x48\x86\xf7\x0d\x01\x01\x01\x05\x00\x03' + self.der_length(len(pk)) + pk
    #     pk = '\x30' + self.der_length(len(pk)) + pk
    #     pk = '-----BEGIN PUBLIC KEY-----\n' + base64.encodestring(pk) + '-----END PUBLIC KEY-----'
    #     self.public_key_x501 = BIO.MemoryBuffer(pk)

    def verify_public(self):
        return  # key verification is a pain in the ass
        #rsa = RSA.load_pub_key_bio(self.public_key_x501)
        #util.debugLog(self, "public key loaded successfully")

    def verify_private(self):
        return
        #rsa = RSA.load_key_bio(self.private_key)
        #util.debugLog(self, "private key loaded successfully")
