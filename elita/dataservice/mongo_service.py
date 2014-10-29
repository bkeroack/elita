__author__ = 'bkeroack'

import logging
import elita.util
import bson

class MongoService:
    # logspam
    #__metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, db):
        '''
        @type db = pymongo.database.Database
        '''
        assert db
        self.db = db

    def create_new(self, collection, keys, classname, doc, remove_existing=True):
        '''
        Creates new document in collection. Optionally, remove any existing according to keys (which specify how the
        new document is unique)

        Returns id of new document
        '''
        assert elita.util.type_check.is_string(collection)
        assert elita.util.type_check.is_dictlike(keys)
        assert elita.util.type_check.is_optional_str(classname)
        assert elita.util.type_check.is_dictlike(doc)
        assert collection
        # keys/classname are only mandatory if remove_existing=True
        assert (keys and classname and remove_existing) or not remove_existing
        if classname:
            doc['_class'] = classname
        existing = None
        if remove_existing:
            existing = [d for d in self.db[collection].find(keys)]
            for k in keys:
                doc[k] = keys[k]
            if '_id' in doc:
                del doc['_id']
        id = self.db[collection].save(doc, fsync=True)
        logging.debug("new id: {}".format(id))
        if existing and remove_existing:
            logging.warning("create_new found existing docs! deleting...(collection: {}, keys: {})".format(collection, keys))
            keys['_id'] = {'$ne': id}
            self.db[collection].remove(keys)
        return id

    def modify(self, collection, keys, path, doc_or_obj):
        '''
        Modifies document with the keys in doc. Does so atomically but remember that any key will overwrite the existing
        key.

        doc_or_obj could be None, zero, etc.

        Returns boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert path
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection and keys
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        canonical_id = dlist[0]['_id']
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; using the first and removing others"
                            .format(keys, collection))
            keys['_id'] = {'$ne': canonical_id}
            self.db[collection].remove(keys)
        path_dot_notation = '.'.join(path)
        result = self.db[collection].update({'_id': canonical_id}, {'$set': {path_dot_notation: doc_or_obj}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def save(self, collection, doc):
        '''
        Replace a document completely with a new one. Must have an '_id' field
        '''
        assert collection
        assert elita.util.type_check.is_string(collection)
        assert elita.util.type_check.is_dictlike(doc)
        assert '_id' in doc

        return self.db[collection].save(doc)

    def delete(self, collection, keys):
        '''
        Drop a document from the collection

        Return whatever pymongo returns for deletion
        '''
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection and keys
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; removing all".format(keys,
                                                                                                        collection))
        return self.db[collection].remove(keys, fsync=True)

    def update_roottree(self, path, collection, id, doc=None):
        '''
        Update the root tree at path [must be a tuple of indices: ('app', 'myapp', 'builds', '123-foo')] with DBRef
        Optional doc can be passed in which will be inserted into the tree after adding DBRef field

        Return boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert elita.util.type_check.is_string(collection)
        assert id.__class__.__name__ == 'ObjectId'
        assert elita.util.type_check.is_optional_dict(doc)
        path_dot_notation = '.'.join(path)
        root_tree_doc = doc if doc else {}
        root_tree_doc['_doc'] = bson.DBRef(collection, id)
        result = self.db['root_tree'].update({}, {'$set': {path_dot_notation: root_tree_doc}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def rm_roottree(self, path):
        '''
        Delete/remove the root_tree reference at path
        '''
        assert hasattr(path, '__iter__')
        assert path
        path_dot_notation = '.'.join(path)
        result = self.db['root_tree'].update({}, {'$unset': {path_dot_notation: ''}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def get(self, collection, keys, multi=False, empty=False):
        '''
        Thin wrapper around find()
        Retrieve a document from Mongo, keyed by name. Optionally, if duplicates are found, delete all but the first.
        If empty, it's ok to return None if nothing matches

        Returns document
        @rtype: dict | list(dict) | None
        '''
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist or empty
        if len(dlist) > 1 and not multi:
            logging.warning("Found duplicate entries ({}) for query {} in collection {}; dropping all but the first"
                            .format(len(dlist), keys, collection))
            keys['_id'] = {'$ne': dlist[0]['_id']}
            self.db[collection].remove(keys)
        return dlist if multi else (dlist[0] if dlist else dlist)

    def dereference(self, dbref):
        '''
        Simple wrapper around db.dereference()
        Returns document pointed to by DBRef

        @type id: bson.DBRef
        '''
        assert dbref
        assert dbref.__class__.__name__ == 'DBRef'
        return self.db.dereference(dbref)

