# Copyright 2010 Matthew Shanker
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

#####################################################################
# USAGE
# 
# of = LocalOFStore('/my/OmniFocus.ofocus')
#
# for task in of.tasks:
#     print task
# for folder in of.folders:
#     print folder
# for context in of.contexts:
#     print context
# for entry in of.all:
#     print entry
#
#---------------------------
#
# of = WebDAVOFStore('www.myserver.com/dav/user/', username='user', password='pass', https=True)
# 
# for task in [t for t in of.tasks if 'context' in t]:
#    print "%s -> %s"%(of.getById(task['context']), task['name'])
#
# of.prettyPrint()
#
#####################################################################

import re
import httplib
import base64
import glob
import copy
from lxml import etree
from zipfile import ZipFile
from cStringIO import StringIO

#{ OFEntry
class OFEntry:
    def __init__(self, node):
        self._ns = {'n': node.nsmap[None]}
        self.type = node.tag
        self.id = node.get('id')
        self.name = self._getText('n:name', node)
        self.added = self._getText('n:added', node)
        self.modified = self._getText('n:modified', node)
        self.rank = self._getText('n:rank', node) 

    def _getText(self, tag, node):
        return "".join([n.text for n in node.xpath(tag,namespaces=self._ns)])
    def _getAttr(self, tag, node):
        return "".join([n for n in node.xpath(tag,namespaces=self._ns)])
    def _getChildren(self, tag, node):
        return node.xpath(tag, namespaces=self._ns)

#}
#{ OFTask
class OFTask(OFEntry):
    def __init__(self, node):
        OFEntry.__init__(self, node)
        self.due = self._getText('n:due', node)
        self.parent = self._getAttr('n:task/@idref', node)
        self.context = self._getAttr('n:context/@idref', node)
        self.order = self._getText('n:order', node) 
        if len(self._getChildren('n:project', node)) > 0:
            p = self._getChildren('n:project', node)[0]
            self.project = True
            self.last_review = self._getText('n:last-review', p)
            self.review_interval = self._getText('n:review-interval', p)
            self.parent = self._getAttr('n:folder/@idref', p)
        if len(self._getChildren('n:inbox', node)) > 0:
            self.inbox = True
        self._orig = copy.deepcopy(self)
#}
#{ OFFolder
class OFFolder(OFEntry):
    def __init__(self, node):
        OFEntry.__init__(self, node)
        self.parent = self._getAttr('n:folder/@idref', node) 
        self._orig = copy.deepcopy(self)
#}
#{ OFContext
class OFContext(OFEntry):
    def __init__(self, node):
        OFEntry.__init__(self, node)
        self.parent = self._getAttr('n:context/@idref', node) 
        self._orig = copy.deepcopy(self)
#}

#{ OFStore
class OFStore:
    def __init__(self):
        self._data = {'': None}

    def _parseSetting(self, node):
        return None
    def _parseContext(self, node):
        return OFContext(node)
    def _parseFolder(self, node):
        return OFFolder(node)
    def _parseTask(self, node):
        return OFTask(node)
    def _parsePersective(self, node):
        return None

    def _parseString(self,contents):
        self._parserfactory = {
         '{http://www.omnigroup.com/namespace/OmniFocus/v1}setting': self._parseSetting,
         '{http://www.omnigroup.com/namespace/OmniFocus/v1}context': self._parseContext,
         '{http://www.omnigroup.com/namespace/OmniFocus/v1}folder': self._parseFolder,
         '{http://www.omnigroup.com/namespace/OmniFocus/v1}task': self._parseTask,
         '{http://www.omnigroup.com/namespace/OmniFocus/v1}perspective': self._parsePersective
         }

        try:
            self._tree = etree.fromstring(contents)

            for elmnt in self._tree.xpath('*'):
                if elmnt.get('op') == 'delete' and elmnt.get('id') in self._data:
                    del self._data[elmnt.get('id')]
                else:
                    obj = self._parserfactory[elmnt.tag](elmnt)
                    if obj != None:
                        self._data[obj.id] = obj
        except Exception, e:
            print contents
            raise e

    def _gettasks(self):
        return filter(lambda x:x!=None and x.type.endswith('task'),self._data.values())
    tasks = property(_gettasks)
    def _getfolders(self):
        return filter(lambda x:x!=None and x.type.endswith('folder'),self._data.values())
    folders = property(_getfolders)
    def _getcontexts(self):
        return filter(lambda x:x!=None and x.type.endswith('context'),self._data.values())
    contexts = property(_getcontexts)
    def _getall(self):
        return filter(lambda x:x!=None,self._data.values())
    all = property(_getall)
    def getById(self, id):
        return self._data[id]

    def delete(self, id, recurse=False):
        return True

    def _printContextTree(self, node, level):
        print '    '*level+node.name
        for child in filter(lambda c:c.parent == node.id, self.contexts):
            self._printContextTree(child, level+1)
        for child in filter(lambda c:c.context == node.id, self.tasks):
            self._printContextTree(child, level+1)

    def _printProjectTree(self, node, level):
        print '    '*level+node.name
        for child in filter(lambda c:hasattr(c, 'parent') and c.parent == node.id, self.all):
            self._printProjectTree(child, level+1)

    def prettyPrint(self):
        print "Context\n---------------------"
        for context in filter(lambda c:c.parent == '', self.contexts):
            self._printContextTree(context, 0)
        print "Project\n---------------------"
        for project in filter(lambda c:c.parent == '', self.folders):
            self._printProjectTree(project, 0)
#}
#{ WebDAVOFStore
class WebDAVOFStore(OFStore):
    def __init__(self, url, username=None, password=None, https=False):
        OFStore.__init__(self)

        self._domain = url.split('/')[0]
        self._path = '/'+'/'.join(url.split('/')[1:])+'OmniFocus.ofocus/'
        self._username = username
        self._password = password
        self._https = https
        response = self._fetchFileContents('')

        files = filter(lambda x: x.endswith('.zip'), [m.groups()[0] for m in 
            map(lambda x:re.search('.*href="([^>]*)"',x), response.split('\n'))
            if m != None])

        for file in sorted(files):
            try:
                s = StringIO()
                s.write(self._fetchFileContents(file))
                self._parseString(ZipFile(s).read('contents.xml'))
            except Exception, e:
                print "Error fetching/parsing file %s: %s"%(file, e)

    def _fetchFileContents(self, filename):
        if self._https:
            conn = httplib.HTTPSConnection(self._domain)
        else:
            conn = httplib.HTTPConnection(self._domain)

        conn.putrequest('GET', self._path+filename)
        if self._username != None:
            conn.putheader('Authorization', 'Basic '+base64.encodestring(self._username+':'+self._password))
        conn.endheaders()
        response = conn.getresponse()
        if response.status != 200:
            raise Exception('%s\nHTTP/S Status: %d, %s'%
                    (self._domain+self._path, response.status, response.reason))
        return response.read()
#}
#{ LocalOFStore
class LocalOFStore(OFStore):
    def __init__(self, path):
        OFStore.__init__(self)

        files = glob.glob(path+'/*.zip')

        for file in sorted(files):
            try:
                self._parseString(ZipFile(open(file)).read('contents.xml'))
            except Exception, e:
                print "Error fetching/parsing file %s: %s"%(file, e)
#}
