__author__ = 'bkeroack'

import ec2
import salt.client

class QualType:
    Corp = 0
    EC2 = 1
    CorpMaster = 'laxqualmaster'
    EC2Master = 'qualmaster001'

class QualTypeUnknown(Exception):
    pass


class ProvisionQual:
    def __init__(self, qual_type, build):
        self.qual_type = qual_type
        self.build = build
        assert self.build.__class__.__name__ == 'Build'

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


class SaltClient:
    def __init__(self):
        self.client = salt.client.LocalClient()

    def powershell(self, target, cmd, target_type='glob', timeout=120):
        return self.client.cmd(target, 'cmd.run', cmd, timeout=timeout, expr_form=target_type, shell='powershell')

    def cmd(self, target, cmd, args, target_type='glob', timeout=60):
        return self.client.cmd(target, cmd, args, timeout=timeout, expr_form=target_type)

    def ping(self, target):
        return