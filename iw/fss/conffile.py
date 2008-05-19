# -*- coding: utf-8 -*-
## FileSystemStorage
## Copyright (C)2006 Ingeniweb

## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program; see the file COPYING. If not, write to the
## Free Software Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
"""
The FileSystemStorage tool
$Id$
"""

__version__ = "$Revision$"
__docformat__ = 'restructuredtext'


# Python imports
import os
import time
import Globals

# Zope imports
from zope.interface import implements
#getSite return the context-dependent plone site
from zope.app.component.hooks import getSite
# CMF imports
from Products.CMFCore.utils import getToolByName

# Products imports
from iw.fss.utils import rm_file
from iw.fss.FileSystemStorage import FileSystemStorage
from iw.fss.utils import getFieldValue
from iw.fss.utils import FSSMessageFactory as _
from iw.fss.utils import patchedTypesRegistry
from iw.fss.config import ZCONFIG, CONFIG_FILE
from iw.fss import strategy as fss_strategy
from iw.fss.interfaces import IConf

# {storage-strategy (from config file): strategy class, ...}
_strategy_map = {
    'flat': fss_strategy.FlatStorageStrategy,
    'directory': fss_strategy.DirectoryStorageStrategy,
    'site1': fss_strategy.SiteStorageStrategy,
    'site2': fss_strategy.SiteStorageStrategy2
    }


class ConfFile(object):
    """Tool for FileSystem storage"""

    implements(IConf)
    rdf_enabled = False
    rdf_script = ""
    def initProperties(self):
        """Init properties"""

        default_path = os.path.join(Globals.INSTANCE_HOME, 'var')
        self.storage_path = default_path
        self.backup_path = default_path
        self.rdf_enabled = False

    def isRDFEnabled(self):
        """Returns true if RDF is automaticaly generated when file added"""

        return self.rdf_enabled

    def enableRDF(self, enabled):
        """Enable rdf or not"""

        self.rdf_enabled = bool(enabled)


    def getRDFScript(self):
        """Returns rdf script used to generate RDF on files"""

        return self.rdf_script


    def setRDFScript(self, rdf_script):
        """Set rdf script used to generate RDF on files"""

        self.rdf_script = rdf_script


    def getStorageStrategy(self):
        """Returns the storage strategy"""

        global _strategy_map
        portal = getSite()
        portal_path = '/'.join(portal.getPhysicalPath())
        strategy_class = _strategy_map[ZCONFIG.storageStrategyForSite(portal_path)]
        return strategy_class(
            ZCONFIG.storagePathForSite(portal_path),
            ZCONFIG.backupPathForSite(portal_path))


    def getUIDToPathDictionnary(self):
        """Returns a dictionnary

        For one uid (key) give the correct path (value)
        """

        ctool = getToolByName(getSite(), 'uid_catalog')
        brains = ctool(REQUEST={})
        return dict([(x['UID'], x.getPath()) for x in brains])


    def getPathToUIDDictionnary(self):
        """Returns a dictionnary

        For one path (key) give the correct UID (value)
        """

        ctool = getToolByName(getSite(), 'uid_catalog')
        brains = ctool(REQUEST={})
        return dict([(x.getPath(), x['UID']) for x in brains])


    def getFSSBrains(self, items):
        """Returns a dictionnary.

        For one uid, returns a dictionnary containing of fss item stored on
        filesystem:
        - uid: UID of content
        - path: Path of content
        - name: Name of field stored on filesystem
        - size: Size in octets of field value stored on filesystem
        - fs_path: Path on filesystem where the field value is stored
        """

        if not items:
            return []

        # Get the first item of items list and check if item has uid or path key
        if not items[0].has_key('uid'):
            # Use path to uid dictionnary
            path_to_uid = self.getPathToUIDDictionnary()
            for item in items:
                item['uid'] = path_to_uid.get(item['path'], None)
        else:
            # Use uid to path dictionnary
            uid_to_path = self.getUIDToPathDictionnary()
            for item in items:
                item['path'] = uid_to_path.get(item['uid'], None)

        return items


    def getStorageBrains(self):
        """Returns a list of brains in storage path"""

        strategy = self.getStorageStrategy()
        items = strategy.walkOnStorageDirectory()
        return self.getFSSBrains(items)


    def getStorageBrainsByUID(self, uid):
        """ Returns a list containing all brains related to fields stored
        on filesystem of object having the specified uid"""

        return [x for x in self.getStorageBrains() if x['uid'] == uid]


    def getBackupBrains(self):
        """Returns a list of brains in backup path"""

        strategy = self.getStorageStrategy()
        items = strategy.walkOnBackupDirectory()
        return self.getFSSBrains(items)


    def updateFSS(self):
        """
        Update FileSystem storage
        """

        storage_brains = self.getStorageBrains()
        backup_brains = self.getBackupBrains()

        not_valid_files = tuple([x for x in storage_brains if x['path'] is None])
        not_valid_backups = tuple([x for x in backup_brains if x['path'] is not None])
        strategy = self.getStorageStrategy()

        # Move not valid files in backup
        for item in not_valid_files:
            strategy.unsetValueFile(**item)

        # Move not valid backups in file storage
        for item in not_valid_backups:
            strategy.restoreValueFile(**item)


    def removeBackups(self, max_days):
        """
        Remove backups older than specified days
        """

        backup_brains = self.getBackupBrains()
        valid_backups = [x for x in backup_brains if x['path'] is None]
        current_time = time.time()

        for item in valid_backups:
            one_day = 86400 # One day 86400 seconds
            modified = item['modified']
            seconds = int(current_time) - int(modified.timeTime())
            days = int(seconds/one_day)

            if days >= max_days:
                rm_file(item['fs_path'])


    def updateRDF(self):
        """Add RDF files to fss files"""

        rdf_script = self.getRDFScript()
        storage_brains = self.getStorageBrains()
        strategy = self.getStorageStrategy()

        for item in storage_brains:
            instance_path = item['path']
            if instance_path is None:
                continue

            try:
                instance = self.restrictedTraverse(instance_path)
            except AttributeError:
                # The object doesn't exist anymore, we continue
                continue
            name = item['name']
            field = instance.getField(name)
            if field is None:
                continue
            storage = field.getStorage(instance)
            if not isinstance(storage, FileSystemStorage):
                continue

            # Get FSS info
            info = storage.getFSSInfo(name, instance)
            if info is None:
                continue

            # Call the storage strategy
            rdf_value = info.getRDFValue(name, instance, rdf_script=rdf_script)
            strategy.setRDFFile(rdf_value, uid=item['uid'], name=name)


    def getFSSItem(self, instance, name):
        """Get value of fss item.
        This method is called from fss_get script.

        @param instance: Object containing FSS item
        @param name: Name of FSS item to get
        """

        return getFieldValue(instance, name)


    def patchedTypesInfo(self):
        """A TALES friendly summary of content types with storage changed to FSS"""

        out = []
        for type_class, fields_to_storages in patchedTypesRegistry.items():
            feature = {'klass': str(type_class)}
            feature['fields'] = [{'fieldname': fn, 'storage': str(st.__class__)}
                                 for fn, st in fields_to_storages.items()]
            out.append(feature)
        return out


    def siteConfigInfo(self):
        """A TALES friendly configuration info mapping for this Plone site"""

        portal = getToolByName(getSite(), 'portal_url').getPortalObject()
        portal_path = '/'.join(portal.getPhysicalPath())
        return {
            'config_file': CONFIG_FILE,
            'strategy': ZCONFIG.storageStrategyForSite(portal_path),
            'storage_path': ZCONFIG.storagePathForSite(portal_path),
            'backup_path': ZCONFIG.backupPathForSite(portal_path)
            }


    def globalConfigInfo(self):
        """A TALES friendly configuration info mapping for global configuration"""

        return {
            'config_file': CONFIG_FILE,
            'strategy': ZCONFIG.storageStrategyForSite('/'),
            'storage_path': ZCONFIG.storagePathForSite('/'),
            'backup_path': ZCONFIG.backupPathForSite('/')
            }


    def formattedReadme(self):
        """README.txt (reStructuredText) transformed to HTML"""

        from reStructuredText import HTML
        readme_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'README.txt')
        return HTML(file(readme_path).read(), report_level=100) # No errors/warnings -> faster

