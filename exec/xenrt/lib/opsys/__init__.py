import xenrt
from zope.interface import implements, providedBy

oslist = []


class OS(object):
    implements(xenrt.interfaces.OS)

    _allInstallMethods = {xenrt.interfaces.InstallMethodPV: xenrt.InstallMethod.PV,
                          xenrt.interfaces.InstallMethodIso: xenrt.InstallMethod.Iso,
                          xenrt.interfaces.InstallMethodIsoWithAnswerFile: xenrt.InstallMethod.IsoWithAnswerFile}

    def __init__(self, distro, parent):
        self.parent = xenrt.interfaces.OSParent(parent)
        self.distro = distro
        self.password = None
        self.viridian = False
        self.__installMethod = None

    def findPassword(self):
        """Try some passwords to determine which to use"""
        return

    def populateFromExisting(self):
        pass

    @property
    def installMethod(self):
        return self.__installMethod

    @installMethod.setter
    def installMethod(self, value):
        assert value in self.supportedInstallMethods
        self.__installMethod = value

    @property
    def supportedInstallMethods(self):
        # We base this on interfaces
        interfaces = providedBy(self)
        return [method for intf, method in self._allInstallMethods.items() if intf in interfaces]

    @staticmethod
    def knownDistro(distro):
        return False

    def assertHealthy(self):
        raise xenrt.XRTError("Not implemented")

    def getLogs(self, path):
        pass

def registerOS(os):
    oslist.append(os)


def osFactory(distro, parent):
    for o in oslist:
        if o.knownDistro(distro):
            return o(distro, parent)
    raise xenrt.XRTError("No class found for distro %s" % distro)

__all__ = ["OS", "registerOS"]

from xenrt.lib.opsys.linux import *
from xenrt.lib.opsys.debian import *
from xenrt.lib.opsys.windows import *
from xenrt.lib.opsys.windowspackages import *
from xenrt.lib.opsys.rhel import *
from xenrt.lib.opsys.sles import *
