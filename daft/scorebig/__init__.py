__author__ = 'bkeroack'

import package
import action


def register_apps():
    return ['scorebig']


def register_package():
    return {'PACKAGE': package.ScoreBig_Packages}


def register_actions():
    return {'BUILD_UPLOAD_SUCCESS': action.UploadBuildAction}
