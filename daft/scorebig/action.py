__author__ = 'bkeroack'

import ec2
import salt.client

class QualType:
    Corp = 0
    EC2 = 1

class QualTypeUnknown(Exception):
    pass


class ProvisionQual:
    def __init__(self, qual_type):
        self.qual_type = qual_type

    def start(self):
        self.verify_master_server()
        self.copy_build()
        self.shut_down_master()
        self.take_snapshot()
        self.create_qual()
        self.setup_qual()
        self.setup_dns()



    # generic master server:
    #   - verify up
    #   - copy build over
    #   - (shut down - optional?)
    # generic snapshot:
    #   - take snapshot of build volume
    # generic new server:
    #   - create new server based on generic server image (ami/vhd)
    # loop on creation until up
    # generic uptime tasks:
    #   - IIS bindings
    #   - service start
    #   - bootstrapping
    # generic DNS
    #   - create DNS A record


class QualMasterServer:
    def __init__(self, qual_type):
        if qual_type == QualType.Corp:
            self.name = "laxqualmaster"
        elif qual_type == QualType.EC2:
            self.name = "qualmaster001"
        else:
            raise QualTypeUnknown

    def verify(self):
        pass


class SaltClient:
    def __init__(self):
        self.client = salt.client.LocalClient()

    def powershell(self, target, cmd):
        self.client.cmd()
