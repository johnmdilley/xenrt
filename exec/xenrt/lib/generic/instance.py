import xenrt

class Instance(object):

    def __init__(self, toolstack, name, distro, vcpus, memory, vifs=None, rootdisk=None, extraConfig={}):
        self.toolstack = toolstack
        self.toolstackId = None
        self.name = name
        self.distro = distro
        self.vcpus = vcpus
        self.memory = memory
        self.extraConfig = extraConfig
        self.mainip = None

        self.os = xenrt.lib.opsys.OSFactory(self.distro, self)

        self.rootdisk = rootdisk or self.os.defaultRootdisk
        self.vifs = vifs or [("%s0" % (self.os.vifStem), None, xenrt.randomMAC(), None)]

    @property
    def hypervisorType(self):
        return self.toolstack.hypervisorType(self)

    def poll(self, state, timeout=600, level=xenrt.RC_FAIL, pollperiod=15):
        """Poll for reaching the specified state"""
        deadline = xenrt.timenow() + timeout
        while 1:
            status = self.getPowerState()
            if state == status:
                return
            if xenrt.timenow() > deadline:
                xenrt.XRT("Timed out waiting for VM %s to be %s" %
                          (self.name, state), level)
            xenrt.sleep(15, log=False)

    def getIP(self, timeout=600, level=xenrt.RC_ERROR):
        if self.mainip:
            return self.mainip
        return self.toolstack.getIP(self, timeout, level)
        
    def start(self, on=None, timeout=600):
        self.toolstack.startInstance(self, on)
        self.os.waitForBoot(timeout)

    def reboot(self, force=False, timeout=600):
        self.toolstack.rebootInstance(self, force)
        self.os.waitForBoot(timeout)

    def stop(self, force=False):
        self.toolstack.stopInstance(self, force)

    def suspend(self):
        self.toolstack.suspendInstance(self)

    def resume(self, on=None):
        self.toolstack.resumeInstance(self, on)

    def migrate(self, to, live=True):
        self.toolstack.migrateInstance(self, to, live)

    def setPowerState(self, powerState):
        transitions = {}
        transitions[xenrt.PowerState.up] = {}
        transitions[xenrt.PowerState.up][xenrt.PowerState.down] = [self.stop]
        transitions[xenrt.PowerState.up][xenrt.PowerState.suspended] = [self.suspend]

        transitions[xenrt.PowerState.down] = {}
        transitions[xenrt.PowerState.down][xenrt.PowerState.up] = [self.start]
        transitions[xenrt.PowerState.down][xenrt.PowerState.suspended] = [self.start, self.suspend]

        transitions[xenrt.PowerState.suspended] = {}
        transitions[xenrt.PowerState.suspended][xenrt.PowerState.up] = [self.resume]
        transitions[xenrt.PowerState.suspended][xenrt.PowerState.down] = [self.resume, self.stop]
        
        curState = self.getPowerState()

        try:
            ts = transitions[curState][powerState]
        except:
            xenrt.TEC().logverbose("No transition needed for %s to %s" % (curState, powerState))
        else:
            for t in ts:
                t()

    def getPowerState(self):
        return self.toolstack.getInstancePowerState(self)

    def ejectIso(self):
        return self.toolstack.ejectIso(self)

__all__ = ["Instance"]
