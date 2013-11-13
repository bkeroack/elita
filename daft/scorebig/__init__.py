__author__ = 'bkeroack'

import package
import action


def register_apps():
    return ['scorebig']


def register_package():
    return {'scorebig': {'PACKAGE': package.ScoreBig_Packages}}


def register_hooks():
    return {'scorebig': {'BUILD_UPLOAD_SUCCESS': action.UploadBuildHook}}

def register_actions():
    return {'scorebig': [action.CleanupOldBuilds]}
