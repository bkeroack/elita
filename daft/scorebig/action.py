__author__ = 'bkeroack'

import logging
import requests
import re
import datetime
import pytz


def debugLog(self, msg):
    logging.debug("ScoreBig: Action: {}: {}".format(self.__class__.__name__, msg))


class QualType:
    Corp = 0
    EC2 = 1
    CorpMaster = 'laxqualmaster'
    EC2Master = 'qualmaster001'


class QualTypeUnknown(Exception):
    pass


class UploadBuildHook:
    def __init__(self, datasvc, **kwargs):
        #pattern match for prod Skynet registration
        self.rx = re.compile("^[0-9]{1,8}-(master|develop|regression).*")
        self.build_name = kwargs['build_name']
        self.datasvc = datasvc

    def go(self):
        ret = True
        if self.rx.match(self.build_name):
            debugLog(self, "regexp matches: {}".format(self.build_name))
            ret = RegisterBuildSkynet(self.build_name).register()
        ret2 = RegisterBuildSkynetQA(self.build_name).register()
        return ret and ret2  # awkward but we want both to run always


class RegisterBuild:
    def __init__(self, url, build_name):
        self.url = url
        self.build_name = build_name

    def register(self):
        url = self.url.format(self.build_name)
        debugLog(self, "url: {}".format(url))
        try:
            r = requests.post(url, timeout=90)  # skynetqa can be super slow
        except requests.ConnectionError:
            debugLog(self, "ConnectionError")
            return False
        except requests.Timeout:
            debugLog(self, "Timeout")
            return False
        resp = str(r.text).encode('ascii', 'ignore')
        debugLog(self, "response: {}".format(resp))
        debugLog(self, "encoding: {}".format(r.encoding))
        return "ok" in resp


class RegisterBuildSkynet(RegisterBuild):
    def __init__(self, build_name):
        url = "http://skynet.scorebiginc.com/Hacks/RegisterBuild?buildNumber={}"
        RegisterBuild.__init__(self, url, build_name)


class RegisterBuildSkynetQA(RegisterBuild):
    def __init__(self, build_name):
        url = "http://skynetqa.scorebiginc.com/DevQaTools/RegisterBuild?buildNumber={}"
        #url = "http://laxsky001/DevQaTools/RegisterBuild?buildNumber={}"  # for local testing
        RegisterBuild.__init__(self, url, build_name)


class CleanupOldBuilds:
    def __init__(self, datasvc):
        self.now = datetime.datetime.now().replace(tzinfo=pytz.utc)
        self.datasvc = datasvc

    def start(self, params, verb):
        debugLog(self, "running")
        try:
            days = int(params['days'])
        except:
            return {"CleanupOldBuilds": {"status": "error", "result": "incorrect days parameter (must be integer)"}}
        cutoff = self.now - datetime.timedelta(days=days)
        debugLog(self, "days: {}".format(params['days']))
        builds = self.datasvc.GetBuilds("scorebig")
        i = len(builds)
        dlist = list()
        for b in builds:
            debugLog(self, "build: {}".format(b))
            buildobj = self.datasvc.GetBuild("scorebig", b)
            #if it doesn't have timestamp it's super old
            if (not hasattr(buildobj, "created_datetime")) or buildobj.created_datetime < cutoff:
                debugLog(self, "...removing build: {}".format(buildobj.build_name))
                dlist.append(buildobj.build_name)
        d = 0
        for b in dlist:
            if params["delete"] == "true":
                self.datasvc.DeleteBuild("scorebig", b)
                d += 1
        debugLog(self, "{} deleted; {} eligible; {} total builds".format(d, len(dlist), i))
        return {"CleanupOldBuilds": {"status": "ok",
                                     "parameters": {
                                         "days": params['days'],
                                         "delete": params['delete']
                                     },
                                     "result": {
                                         "deleted": d,
                                         "eligible": len(dlist),
                                         "total": i
                                     }}}

    @staticmethod
    def params():
        return {"POST": ["delete", "days"]}

