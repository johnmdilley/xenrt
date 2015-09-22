﻿from abc import ABCMeta, abstractmethod
import xenrt
import re
import datetime

class SSFile(object):

    def __init__(self, name, location):
        self.setName(name)
        self.setLocation(location)

    def getName(self):
        return self.name

    def setName(self, name):
        self.name = name

    def getLocation(self):
        return self.location

    def setLocation(self, location):
        self.location = location

class SimpleServer(object):

    def __init__(self, port, ssFiles, guest):
        self.ssFiles = ssFiles
        self.port = port
        self.guest = guest

    def isPinged(self, wait):
        xenrt.sleep(wait)
        host = self.guest.host
        line = host.execdom0("tail -n 1 logs/server.log")
        timeStr = re.search('(\d\d:){2}\d\d',line)
        logTime = (datetime.datetime.strptime(timeStr,'%H:%M:%S')+datetime.timedelta(seconds=wait)).time()
        nowTime = datetime.datetime.now().time()
        if logTime < nowTime:
            return False
        else:
            return True

    def moveFile(self, ssFile):
        host = self.guest.host
        if ssFile.location == "store/":
            host.execDom0("mv store/{0} {0}".format(ssFile.name))
            ssFile.location = ""
        else:
            host.execDom0("mv {0} store/{0}".format(ssFile.name))
            ssFile.location = "store/"

    def addFile(self, ssFile, key):
        self.ssFiles[key] = ssFile

    def removeFile(self, key):
        self.ssFiles.pop(key,None)

    def addRedirect(self, dirInit, dirRe):
        pass

    def removeRedirect(self, dir):
        pass

    def getIP(self):
        return self.guest.getIP()
        
class DotNetAgent(object):

    def __init__(self, guest):
        self.licensedFeatures = {'VSS':VSS(),'AutoUpdate':AutoUpdate()}
        self.guest = guest

    def restartAgent(self):
        pass

    def agentVersion(self):
        pass

    def getLicensedFeature(self,feature):
        ''' current features are "VSS", "AutoUpdate ''' 
        return self.licensedFeatures[feature]

class LicensedFeature(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isLicensed(self):
        pass

    @abstractmethod
    def checkKeyPresence(self):
        pass

class ActorAbstract(LicensedFeature):


    def __init__(self, actor):
        self.setActor(actor)

    def setActor(self,actor):
        self.actor = actor

    def isActive(self):
        self.actor.isActive()

    def enable(self):
        self.actor.enable()

    def disable(self):
        self.actor.disable()

    def setURL(self,url):
        self.actor.setURL(url)

    def defaultURL(self):
        self.actor.defaultURL()

    def checkKeyPresence(self):
        self.actor.checkKeyPresence()

class ActorImp(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def isActive(self):
        pass

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass

    @abstractmethod
    def setURL(self, url):
        pass

    @abstractmethod
    def defaultURL(self):
        pass

    @abstractmethod
    def checkKeyPresence(self):
        pass

class PoolAdmin(ActorImp):

    def isActive(self):
        pass

    def enable(self):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-confg:auto_update_enabled=true"% host.getPool().getUUID())

    def disable(self):
        pass

    def setURL(self,url):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-confg:auto_update_url=%s"%(host.getPool().getUUID(),url))

    def defaultURL(self):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-confg:auto_update_url=\"\""%host.getPool().getUUID())

    def checkKeyPresence(self):
        pass

class VMUser(ActorImp):

    def isActive(self):
        pass

    def enable(self):
        pass

    def disable(self):
        pass

    def setURL(self):
        pass

    def defaultURL(self):
        pass

    def checkKeyPresence(self):
        pass

class VSS(LicensedFeature):

    def isSnapshotPossible(self):
        pass

    def isLicensed(self):
        pass

    def checkKeyPresence(self):
        pass

class AutoUpdate(ActorAbstract):

    def checkDownloadedMSI(self):
        pass

    def comapreMSIArch(self):
        pass

    def isLicensed(self):
        pass

    def setUserVMUser(self):
        user = VMUser()
        self.setActor(user)

    def setUserPooAdmin(self):
        user = PoolAdmin()
        self.setActor(user)