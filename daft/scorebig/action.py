__author__ = 'bkeroack'

import logging
import ec2
import salt.client
import requests
import re

class QualType:
    Corp = 0
    EC2 = 1
    CorpMaster = 'laxqualmaster'
    EC2Master = 'qualmaster001'


class QualTypeUnknown(Exception):
    pass


class UploadBuildAction:
    def __init__(self, **kwargs):
        #pattern match for prod Skynet registration
        self.rx = re.compile("^[0-9]{1,8}-(master|develop|sprint).*")
        self.build_name = kwargs['build_name']

    def go(self):
        ret = True
        if self.rx.match(self.build_name):
            logging.debug("UploadBuildAction: regexp matches: {}".format(self.build_name))
            ret = RegisterBuildSkynet(self.build_name).register()
        return ret and RegisterBuildSkynetQA(self.build_name).register()


class RegisterBuild:
    def __init__(self, url, build_name):
        self.url = url
        self.build_name = build_name

    def register(self):
        url = self.url.format(self.build_name)
        logging.debug("ScoreBig: Action: {}: url: {}".format(self.__class__.__name__, url))
        r = requests.post(url)
        resp = str(r.text).encode('ascii', 'ignore')
        logging.debug("ScoreBig: Action: {}: response: {}".format(self.__class__.__name__, resp))
        logging.debug("ScoreBIg: Action: {}: encoding: {}".format(self.__class__.__name__, r.encoding))
        return "ok" in resp


class RegisterBuildSkynet(RegisterBuild):
    def __init__(self, build_name):
        url = "http://skynet.scorebiginc.com/Hacks/RegisterBuild?buildNumber={}"
        RegisterBuild.__init__(self, url, build_name)


class RegisterBuildSkynetQA(RegisterBuild):
    def __init__(self, build_name):
        #url = "http://skynetqa.scorebiginc.com/DevQaTools/RegisterBuild?buildNumber={}"
        url = "http://laxsky001/DevQaTools/RegisterBuild?buildNumber={}"
        RegisterBuild.__init__(self, url, build_name)


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