__author__ = 'bkeroack'

import logging
import collections
import pprint

class RootTree(collections.MutableMapping):

    def __init__(self, db, updater, tree, doc, *args, **kwargs):
        self.pp = pprint.PrettyPrinter(indent=4)
        self.db = db
        self.tree = tree
        self.doc = doc
        self.updater = updater

    def is_action(self):
        return self.doc and self.doc['_class'] == 'ActionContainer'

    def __getitem__(self, key):
        key = self.__keytransform__(key)
        if self.is_action():
            return self.tree[key]
        if key in self.tree:
            if key == '_doc':
                return self.tree[key]
            doc = self.db.dereference(self.tree[key]['_doc'])
            if doc is None:
                logging.debug("RootTree: __getitem__: {}: doc is None: KeyError".format(key))
                raise KeyError
            return RootTree(self.db, self.updater, self.tree[key], doc)
        else:
            logging.debug("RootTree: __getitem__: {}: key not in self.tree: KeyError".format(key))
            raise KeyError

    def __setitem__(self, key, value):
        self.tree[key] = value
        if not self.is_action():     # dynamically populated each request
            pass
            #self.updater.update()

    def __delitem__(self, key):
        del self.tree[key]
        #self.updater.update()
        return

    def __iter__(self):
        return iter(self.tree)

    def __len__(self):
        return len(self.tree)

    def __keytransform__(self, key):
        return key

class RootTreeUpdater:
    '''
    Vestigial remnant of code that was intended to make RootTree 'magic' like ZODB, saving values when added.
    '''
    def __init__(self, tree, db):
        self.tree = tree
        self.db = db

    def clean_actions(self):
        #actions can't be serialized into mongo
        for a in self.tree['app']:
            actions = list()
            if a[0] != '_':
                if "actions" in self.tree['app'][a]:
                    for ac in self.tree['app'][a]['actions']:
                        if ac[0] != '_':
                            actions.append(ac)
                    for action in actions:
                        del self.tree['app'][a]['actions'][action]

    def update(self):
        self.clean_actions()
        root_tree = self.db['root_tree'].find_one()
        self.db['root_tree'].update({"_id": root_tree['_id']}, self.tree)
