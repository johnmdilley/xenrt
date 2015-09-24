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
        xenrt.TEC().logverbose("Checking if Server is pinged")
        xenrt.sleep(wait)
        line = self.guest.execguest("tail -n 1 logs/server.log")
        timeRE = re.search('(\d\d:){2}\d\d',line)
        if not timeRE:
            return False
        logTime = (datetime.datetime.strptime(timeStr.group(0),'%H:%M:%S')+datetime.timedelta(seconds=wait)).time()
        nowTime = datetime.datetime.now().time()
        if logTime < nowTime:
            return False
        else:
            return True

    def moveFile(self, ssFile):
        if ssFile.location == "store/":
            guest.execguest("mv store/{0} {0}".format(ssFile.name))
            ssFile.location = ""
        else:
            guest.execguest("mv {0} store/{0}".format(ssFile.name))
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
        self.guest = guest
        self.os = self.guest.getInstance().os
        self.licensedFeatures = {'VSS':VSS(self.guest,self.os),'AutoUpdate':AutoUpdate(self.guest,self.os)}

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
    def checkKeyPresent(self):
        pass

class ActorAbstract(LicensedFeature):

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

    def checkKeyPresent(self):
        self.actor.checkKeyPresent()

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
    def checkKeyPresent(self):
        pass

class PoolAdmin(ActorImp):

    def __init__(self,guest,os):
        self.guest = guest
        self.os = os

    def isActive(self):
        pass

    def enable(self):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_enabled=true"% host.getPool().getUUID())

    def disable(self):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_enabled=false"% host.getPool().getUUID())

    def setURL(self,url):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_url=%s"%(host.getPool().getUUID(),url))

    def defaultURL(self):
        host = self.guest.host
        host.execDom0("xe pool-param-set uuid=%s guest-agent-config:auto_update_url=\"\""%host.getPool().getUUID())

    def checkKeyPresent(self):
        host = self.guest.host
        return host.xenstoreExists("/guest_agent_features/Guest_agent_auto_update")

class VMUser(ActorImp):

    def __init__(self,guest,os):
        self.guest = guest
        self.os = os

    def isActive(self):
         key = self.os.winRegLookup("HKLM","\\SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate")
         return key != "1"

    def enable(self):
        self.os.winRegAdd("HKLM","\\SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate","SZ","0")

    def disable(self):
        self.os.winRegAdd("HKLM","\\SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate","SZ","1")

    def setURL(self,url):
        self.os.winRegAdd("HKLM","\\SOFTWARE\\Citrix\\XenTools","update_url","SZ","%s"%url)

    def defaultURL(self):
        self.os.winRegDel("HKLM","\\SOFTWARE\\Citrix\\XenTools","update_url")

    def checkKeyPresent(self):
        try:
            key = self.os.winRegLookup("HKLM","\\SOFTWARE\\Citrix\\XenTools","DisableAutoUpdate",healthCheckOnFailure=False)
            if key:
                return True
        except:
            return False

class VSS(LicensedFeature):

    def isSnapshotPossible(self):
        pass

    def isLicensed(self):
        host = self.guest.host
        if host.xenstoreRead("/guest_agent_features/VSS/licensed") == 1:
            return True
        else:
            return False

    def checkKeyPresent(self):
        host = self.guest.host
        if host.xenstoreExists("/guest_agent_features/VSS") == 1:
            return True
        else:
            return False

class AutoUpdate(ActorAbstract):

    def __init__(self, guest, os):
        self.guest = guest
        self.os = os
        self.setUserPoolAdmin()

    def checkDownloadedMSI(self):
        pass

    def compareMSIArch(self):
        pass

    def isLicensed(self):
        host = self.guest.host
        if host.xenstoreRead("/guest_agent_features/Guest_agent_auto_update/licensed") == 1:
            return True
        else:
            return False

    def setUserVMUser(self):
        user = VMUser(self.guest,self.os)
        self.setActor(user)

    def setUserPoolAdmin(self):
        user = PoolAdmin(self.guest,self.os)
        self.setActor(user)