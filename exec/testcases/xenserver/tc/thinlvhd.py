# Test harness for Xen and the XenServer product family
#
# Thin provisioning functional verification test cases. 
# Refer FQP : https://info.citrite.net/pages/viewpage.action?pageId=1228996737
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import re, string
import xenrt, xenrt.lib.xenserver
from xenrt.lazylog import step, log, warning
import testcases.xenserver.tc.lunspace

class _ThinLVHDBase(xenrt.TestCase):
    """Base class of thinprovisioning TCS.
    All TC specific utilities should be implemented in this class."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.srs = self.getThinProvisioningSRs()

    def __buildsmconfig(self, initialAlloc=None, quantumAlloc=None):
        """Create and return sm-config dict with given parameters.

        @param initialAlloc: Initial allocation
        @param quantumAlloc: Quantum allocation

        @return Dict of sm-config
        """

        smconf = {}
        if initialAlloc:
            smconf["initial_allocation"] = str(initialAlloc)
        if quantumAlloc:
            smconf["allocation_quantum"] = str(quantumAlloc)

        return smconf

    def __getsmconfig(self, obj=None):
        """Return smconfig object of given object

        @param obj: sr object, sr uuid string or vdi uuid string. If not given use default sr.

        @return Dict of sm-config
        """

        host = self.host
        if not host:
            host = self.getDefaultHost()
        cli = host.getCLIInstance()

        if not obj:
            obj = self.getDefaultSR()

        if not isinstance(obj, xenrt.lib.xenserver.StorageRepository):
            if obj in host.minimalList("vdi-list"):
                smconfigstr = host.genParamGet("vdi", obj, "sm-config")
            elif obj in host.minimalList("sr-list"):
                # if it is not SR object, then assumes it is sr uuid string.
                sr = xenrt.lib.xenserver.getStorageRepositoryClass(host, obj).fromExistingSR(host, obj)
                smconfigstr = sr.smconfig
            else:
                raise xenrt.XRTError("Only VDI or SR has sm-config option.")
        else:
            smconfigstr = obj.smconfig

        smconf = {}
        for item in smconfigstr.split(";"):
            key, val = item.split(":", 1)
            smconf[key.strip()] = val.strip()

        return smconf

    def getInitialAllocation(self, obj=None):
        """Return initial allocation of SR or VDI"""

        smconf = self.__getsmconfig(obj)
        if "initial_allocation" in smconf:
            return int(smconf["initial_allocation"])

        return None

    def getAllocationQuantum(self, obj=None):
        """Return allocation quantum of SR or VDI"""

        smconf = self.__getsmconfig(obj)
        if "allocation_quantum" in smconf:
            return int(smconf["allocation_quantum"])

        return None

    def createThinSR(self, host=None, name=None, srtype="lvmoiscsi", ietvm=False, size=0, initialAlloc=None, quantumAlloc=None):
        """Creates a SR with given parameters.

        @param host: host instance to handle.
        @param name: name of sr.
        @param srtype: (sub)type of sr.
        @param ietvm: False by default. If it is True, a VM for sr will be created. (Not yet implemented yet)
        @param size: physical size to pass to SR.create()

        @return: created SR object
        """

        if not host:
            host = self.getDefaultHost()
        if not name or len(name) == 0:
            name = srtype + "sr"

        smconf = self.__buildsmconfig(initialAlloc, quantumAlloc)
        if srtype=="lvmoiscsi":
            if size:
                size /= xenrt.MEGA
            else:
                size = 100 * xenrt.KILO # 100 GiB
            if ietvm:
                lun = xenrt.ISCSIVMLun(sizeMB=size)
            else:
                lun = xenrt.ISCSITemporaryLun(size)
            sr = xenrt.lib.xenserver.ISCSIStorageRepository(host, name, True)
            sr.create(lun, subtype="lvm", physical_size=size, findSCSIID=True, noiqnset=True, smconf=smconf)

        elif srtype=="lvmohba":
            fcLun = host.lookup("SR_FCHBA", "LUN0")
            fcSRScsiid = host.lookup(["FC", fcLun, "SCSIID"], None)
            sr = xenrt.lib.xenserver.FCStorageRepository(host,  name, True)
            sr.create(fcSRScsiid, physical_size=size, smconf=smconf)

        else:
            raise xenrt.XRTException("Cannot create Thin-LVHD SR with given srtype %s." % srtype)

        return sr

    def getDefaultSR(self):
        """Find default SR and return SR instance."""
        host = self.host
        if not host:
            host = self.getDefaultHost()

        sruuid = host.lookupDefaultSR()
        return xenrt.lib.xenserver.getStorageRepositoryClass(host, sruuid).fromExistingSR(host, sruuid)

    def getThinProvisioningSRs(self):
        """Find all ThinProvisioning SRs
        
        @return: a list of thin provisioned SRs. [] if none exists.
        """

        host = self.host
        if not host:
            host = self.getDefaultHost()

        srs = []
        for sr in host.asXapiObject().SR(False):
            try:
                srs.append(xenrt.lib.xenserver.getStorageRepositoryClass(host, sr.uuid).fromExistingSR(host, sr.uuid))
            except:
                log("%s type is not supported in SR instantiation." % (sr.srType(),))

        return [sr for sr in srs if sr.thinProvisioning]

    def __getSRObj(self, sr):
        """Return SR instance if it is uuid"""

        host = self.host
        if not host:
            host = self.getDefaultHost()

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            # if it is not SR object, then assumes it is sr uuid string.
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(host, sr).fromExistingSR(host, sr)

        sr.scan()

        return sr

    def getPhysicalUtilisation(self, sr):
        """Return physical utilisation of sr."""

        return int(self.__getSRObj(sr).paramGet("physical-utilisation"))

    def getPhysicalSize(self, sr):
        """Return physical size of sr"""

        return int(self.__getSRObj(sr).paramGet("physical-size"))

    def fillDisk(self, guest, targetDir=None, size=512*xenrt.MEGA, source="/dev/zero"):
        """Fill target disk by creating an empty file with
        given size on the given directory.

        @param guest: Target VM
        @param targetDir: Target directory of the VM. If none is given, use tmp
            by default.
        @param size: Size of the file to create in byte. Use 512M by default.

        If failed to create file due to any reason, raise an xenrt.XRTError.
        """

        if guest.windows:
            # TODO: Windows in guest writing has not been tested.
            if not targetDir:
                targetDir = "C:\\test.bin"
            path = xenrt.TEC().lookup("LOCAL_SCRIPTDIR") + "/progs/winwrite/"
            xenrt.TEC().config.setVariable("WINDOWS_WRITE", guest.compileWindowsProgram(path) + "\\winwrite.exe") 
            data = guest.xmlrpcExec("%s %s" % (xenrt.TEC().lookup("WINDOWS_WRITE"), targetDir), returndata=True)

        else:
            if not targetDir:
                targetDir = guest.execguest("mktemp")

            timeout = 900 + ((size / xenrt.GIGA) * 300) # 15 mins + 5 mins per GIGA
            guest.execguest("dd if=%s of=%s bs=1M count=%d conv=notrunc" % (source, targetDir, size/xenrt.MEGA), timeout=timeout)

    def isThinProvisioning(self, sr):
        """Return whether given SR is thin provision'ed or not

        @param sr: SR object or sr uuid.

        @return: boolean.
        """

        if not isinstance(sr, xenrt.lib.xenserver.StorageRepository):
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(self, sr).fromExistingSR(self, sr)

        return sr.thinProvisioning

    def getPhysicalVDISize(self, vdiuuid, host=None ):
        if not host:
            host = self.getDefaultHost()
        return host.getVDIPhysicalSizeAndType(vdiuuid)[0]

class ThinProvisionVerification(_ThinLVHDBase):
    """ Verify SW thin provisioning available only on LVHD """

    def testThinSRCreation(self, srtype):

        step("Test trying to create thin provisioned %s SR " % (srtype))
        if srtype in ['lvmoiscsi', 'lvmohba']:
            try:
                sr = self.createThinSR(host=self.host, size=200, srtype= srtype)
            except Exception as e:
                xenrt.TEC().logverbose("Failed to create thin provisioned %s SR with Exception : %s " % (srtype, str(e)))
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type %s on the host %s is not thin provisioned" % (srtype, self.host))

        elif srtype =="lvm":
            try:
                sr = ThinLVMStorageRepository(self.host, "thinlvm-sr")
                sr.create(self.host)
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned lvm sr as expected")
            else:
                if self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("Created LVM SR is thin provisioned on the host %s" % (self.host))

        elif srtype =="nfs":
            try:
                sr = ThinNFSStorageRepository(self.host, "thin-nfssr")
                sr.create()
            except Exception:
                xenrt.TEC().logverbose("Unable to create thin provisioned NFS SR")
                raise
            else:
                if not self.isThinProvisioning(sr):
                    raise xenrt.XRTFailure("SR created of type NFS on the host %s is not thin provisioned" % (self.host))

        else:
            raise xenrt.XRTError("Unknown SR Type")

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.srtypes=arglist[0].split(",")

    def run(self, arglist=None):
        for srtype in self.srtypes:
            self.runSubcase("testThinSRCreation", (srtype), "ThinProvision", srtype)

class ThinNFSStorageRepository(xenrt.lib.xenserver.NFSStorageRepository):

    def create(self):
        if xenrt.TEC().lookup("FORCE_NFSSR_ON_CTRL", False, boolean=True):
            # Create an SR using an NFS export from the XenRT controller.
            # This should only be used for small and low I/O throughput
            # activities - VMs should never be installed on this.
            nfsexport = xenrt.NFSDirectory()
            server, path = nfsexport.getHostAndPath("")
        else:
            # Create an SR on an external NFS file server
            share = xenrt.ExternalNFSShare()
            nfs = share.getMount()
            r = re.search(r"([0-9\.]+):(\S+)", nfs)
            server = r.group(1)
            path = r.group(2)

        self.server = server
        self.path = path
        dconf = {}
        smconf = {}
        dconf["server"] = server
        dconf["serverpath"] = path
        smconf["allocation"]="xlvhd"
        self._create("nfs", dconf, smconf=smconf)

class ThinLVMStorageRepository(xenrt.lib.xenserver.LVMStorageRepository):

    def getDevice(self, host):
        data = host.execdom0("cat /etc/firstboot.d/data/default-storage.conf")
        r = re.search(r"PARTITIONS=['\"]*([^'\"\s]+)", data)
        if r:
            device = r.group(1)
        else:
            primarydisk = string.split(host.lookup("OPTION_CARBON_DISKS", "sda"))[0]
            device = xenrt.formPartition("/dev/%s" % (primarydisk), 3)
        return device

    def create(self, host):

        sr = host.getSRs(type="lvm")[0]
        # forget the existing thickly provisioned lvm on the host
        host.forgetSR(sr)
        device=self.getDevice(host)
        smconf = {}
        smconf["allocation"]="xlvhd"
        self._create("lvm",  {"device":device}, smconf=smconf)

class ResetOnBootThinSRSpace(_ThinLVHDBase):
    """Verify that VM release the space when VDI on boot set to reset and VM state set to shutdown"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.goldVM = xenrt.TestCase.getGuest(self, "GoldVM")
        self.srs = self.getThinProvisioningSRs()
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR is found.")

        self.guest = self.goldVM.cloneVM()
        self.uninstallOnCleanup(self.guest)

    def getDigest(self, device="/dev/xvda"):
        digest = self.guest.execguest("md5sum %s" % device).split()[0]
        return digest

    def run(self, arglist=None):

        step("Create a VDI and add it to guest.")
        self.guest.setState("UP")
        vdi = self.host.createVDI(sizebytes=xenrt.GIGA, sruuid=self.srs[0].uuid)
        device = self.guest.createDisk(vdiuuid=vdi, returnDevice=True)

        step("Set VDI to reset on boot.")
        self.guest.setState("DOWN")
        self.host.genParamSet("vdi", vdi, "on-boot", "reset")

        self.guest.setState("UP")
        xenrt.sleep(60)
        srSizeBefore = self.getPhysicalUtilisation(self.srs[0])
        log("Physical SR space allocated for the VDIs before writing: %d" % (srSizeBefore))
        digestBefore = self.getDigest("/dev/%s" % device)
        log("MD5 digest before writing into VDI: %s" % (digestBefore))

        step("Writing some data onto VDI")
        self.fillDisk(self.guest, targetDir="/dev/%s" % device, size=xenrt.GIGA)

        step("Test trying to check SR physical space allocated for the VDI(s)")
        xenrt.sleep(60)
        srSizeAfter = self.getPhysicalUtilisation(self.srs[0])
        log("Physical SR space allocated for the VDIs after writing: %d" % (srSizeAfter))

        # Now shutdown the guest
        step("Rebooting VM to release leaf of VDI") 
        self.guest.reboot()

        step("Test trying to check the SR physical space allocated for the VDI after reset-on-boot VM shutdown")
        xenrt.sleep(60)
        srSizeFinal = self.getPhysicalUtilisation(self.srs[0])
        digestFinal = self.getDigest("/dev/%s" % device)
        log("Physical SR space allocated for the VDI after the VM rebooted: %d" % (srSizeFinal))
        log("MD5 digest after rebooting VM: %s" % (digestFinal))


        # Check digest.
        if digestBefore != digestFinal:
            raise xenrt.XRTFailure("on-boot=reset VDI has not reset after VM reboot.")

        # We expect VM should release the space when it shutdown and VDI on boot set to 'reset'
        if srSizeBefore >= srSizeAfter:
            raise xenrt.XRTFailure("SR physical utilisation has not been increased after writing data in VDI.")

        if srSizeAfter >= srSizeFinal:
            raise xenrt.XRTFailure("SR Physical utilisation is not decreased after reset-on-boot VM rebooted.")


class TCThinProvisioned(_ThinLVHDBase):
    """Verify LUN creates smaller than virtual size of all VDIs contained."""

    def prepare(self, arglist=[]):

        super(TCThinProvisioned, self).prepare(arglist)
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr, vms):

        log("Checking SR: %s..." % sr.name)

        origsize = self.getPhysicalUtilisation(sr)
        self.guests = []
        for vm in range(vms):
            guest = self.host.createGenericLinuxGuest(sr=sr.uuid)
            guest.setState("DOWN")
            guest.preCloneTailor()
            self.uninstallOnCleanup(guest)
            self.guests.append(guest)
 
        aftersize = self.getPhysicalUtilisation(sr)

        if aftersize <= origsize:
            raise xenrt.XRTFailure("SR size is decreased after %d VDI creation. (before: %d, after %d)" %
                    (vms, origsize, aftersize))

        vdisize = 0
        for guest in self.guests:
            for xvdi in guest.asXapiObject().VDI():
                vdisize += xvdi.size()

        if aftersize >= origsize + vdisize:
            raise xenrt.XRTFailure("SR size is bigger than sum of all VDIs on ThinLVHD. (before: %d, after: %d, vdi: %s)" %
                    (origsize, aftersize, vdisize))

    def run(self, arglist=[]):

        args = self.parseArgsKeyValue(arglist)
        vms = 1
        if "vms" in args:
            vms = args["vms"]

        for sr in self.srs:
            self.runSubcase("runCase", (sr, vms), sr.name, "Check %d VDIs" % vms)


class TCSRIncrement(_ThinLVHDBase):
    """Check SR is increment on VDI increase."""

    def prepare(self, arglist=[]):

        super(TCSRIncrement, self).prepare(arglist)

        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR found.")

    def runCase(self, sr):

        log("Checking SR: %s..." % sr.name)

        guest = self.host.createGenericLinuxGuest(sr=sr.uuid)
        guest.setState("DOWN")
        guest.preCloneTailor()
        self.uninstallOnCleanup(guest)
 
        origsize = self.getPhysicalUtilisation(sr)

        self.fillDisk(guest, size = 2 * xenrt.GIGA) # filling 2 GB

        aftersize = self.getPhysicalUtilisation(sr)

        if aftersize <= origsize:
            raise xenrt.XRTFailure("SR size is not growing. (SR: %s, before: %d, after: %d)" %
                (sr.uuid, origsize, aftersize))

    def run(self, arglist=[]):

        for sr in self.srs:
            self.runSubcase("runCase", (sr,), sr.name, "Check %s" % sr.name)

class TCThinAllocationDefault(_ThinLVHDBase):
    """Verify the initial/quantum allocation works for SR and VDI ."""

    # At present, We have 20% for initial allocation and 1% for allocation quantum as default
    DEFAULTINITIAL = 0.2
    DEFAULTQUANTUM = 0.01

    DEFAULTSRTYPE = "lvmoiscsi"

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.SRinitial = args.get("initial_allocation", "").split(',')
        self.SRQuantum = args.get("allocation_quantum", "").split(',')
        self.vdiInitial = args.get("vdi_initial", "").split(',')
        self.vdiQuantum = args.get("vdi_quantum", "").split(',')
        self.srtype = args.get("srtype", self.DEFAULTSRTYPE)
        guest = args.get("guest", None)
        self.sizebytes= 10 * xenrt.MEGA 
        self.host = self.getDefaultHost()
        if not guest:
            self.guest = self.host.createBasicGuest("generic-linux")
        else:
            self.guest = self.getGuest(guest)

    def removeDisk(self,vdiuuid,vbduuid):
        """ Function delete's  the VDI: unplug the VBD and destory the VDI """
        cli = self.host.getCLIInstance()
        cli.execute("vbd-unplug", "uuid=%s" % (vbduuid))
        cli.execute("vbd-destroy", "uuid=%s" % (vbduuid))
        cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))

    def createDisk(self,smconfig={}):
        """ Function Create's the VDI : create the VDI and create VBD and plug it to guest """
        step("Creating a virtual disk and attaching to VM...")
        vdiuuid = self.host.createVDI(self.sizebytes, self.sr.uuid, smconfig=smconfig)
        vbduuid = self.guest.createDisk(vdiuuid = vdiuuid, returnVBD=True)
        return vdiuuid,vbduuid

    def check(self, vdiuuid, initial = DEFAULTINITIAL, quantum = DEFAULTQUANTUM):
        """Calculate the expected size of VDI based on the initial/quantum and
           compare it with actual physical size of VDI

        @param initial : initial allocation decided 
        @param quantum : quantum allocation decided

        @return : None ( This method make the test to fail if the expectedSize is not equal to VDI physical size
        """

        # Check that initial allocation is as expected
        expectedSize = self.sizebytes * ( float(initial) if initial else self.DEFAULTINITIAL)

        # Check that quantum allocation is as expected
        vdiSize = self.getPhysicalVDISize(vdiuuid, self.host)
        expectedSize = vdiSize + self.sizebytes * ( float(quantum) if quantum else self.DEFAULTQUANTUM)

        vbduuid = self.host.genParamGet("vdi", vdiuuid, "vbd-uuids")
        self.fillDisk(self.guest, targetDir = "/dev/%s" %(self.host.genParamGet("vbd", vbduuid, "device")), size = expectedSize - vdiSize)

    def doTest(self, SRinitial, SRquantum):
        """Decides the VDI initial/quantum and initiate the VDI check

        @param SRinitial : initial_allocation of the SR
        @param SRquantum : allocation_quantum of the SR

        @return : None

        """
        smconfig = {}
        for vdiinitial,vdiquantum in map(None, self.vdiInitial, self.vdiQuantum):
            if vdiinitial:
                smconfig["initial_allocation"] = vdiinitial
            else:
                vdiinitial = SRinitial
            if vdiquantum:
                smconfig["allocation_quantum"] = vdiquantum
            else:
                vdiquantum = SRquantum 

            # Create a VDI with a given smconfig
            (vdiuuid,vbduuid) = self.createDisk(smconfig = smconfig)

            # Check initial/quantum is as expected for the VDI
            self.check(vdiuuid, vdiinitial, vdiquantum )

            # Delete the VDI created
            self.removeDisk(vdiuuid, vbduuid)


    def testThinAllocation(self, SRinitial, SRquantum, SRtype):

        smconfig = {}
        # Create thin SR with given config : initial_allocation and allocation_quantum
        self.sr = self.createThinSR(host=self.host, size=200, srtype= SRtype, initialAlloc=SRinitial, quantumAlloc=SRquantum)
 
        # Create a VDI without any smconfig
        (vdiuuid,vbduuid) = self.createDisk()

        # Check initial/quantum is as expected for the VDI
        self.check(vdiuuid, SRinitial, SRquantum)
        
        # Delete the VDI created
        self.removeDisk(vdiuuid, vbduuid)

        self.doTest(SRinitial, SRquantum)
        
        # Delete the SR
        log("Distroying SR.")
        self.sr.destroy()

    def run(self, arglist=[]):

        # Test with Default SR allocation value (initial/quantum) i.e creating SR with no allocation.
        self.runSubcase("testThinAllocation", (None, None, self.srtype,), "ThinAllocation", 'Default %s initial, Default %s quantum'
                        % (self.DEFAULTINITIAL, self.DEFAULTQUANTUM ) )

        # Test with Custom SR allocation values (initial/quantum) i.e creating SR with custom allocation.
        for SRinitial, SRquantum in map(None, self.SRinitial, self.SRQuantum) :
            self.runSubcase("testThinAllocation", (SRinitial, SRquantum, self.srtype,), "ThinAllocation", '%s initial, %s quantum'
                            % (SRinitial, SRquantum ) )

class TCThinAllocation(TCThinAllocationDefault):

    def testingThinAllocation(self, SRinitial = None, SRquantum = None):

        self.doTest(SRinitial, SRquantum)

    def run(self, arglist=[]):

        # Create thin SR with default initial/quantum
        self.sr = self.createThinSR(host = self.host, size=200, srtype = self.srtype)

        self.testingThinAllocation()

        # Test that we can change the default SR config with the custom value 
        for SRinitial, SRquantum in map(None, self.SRinitial, self.SRQuantum):
            self.testingThinAllocation(SRinitial, SRquantum )

class TrimFuncNetAppThinISCSI(testcases.xenserver.tc.lunspace.TrimFuncNetAppISCSI):
    """Test the XenServer TRIM feature on a thin provisioned iSCSI SR using NetApp array"""

    THINPROVISION = True
    SRNAME = "lvmoiscsi-thin"

class TrimFuncNetAppThinFC(testcases.xenserver.tc.lunspace.TrimFuncNetAppFC):
    """Test the XenServer TRIM feature on a thin provisioned Fibre Channel SR using NetApp array"""

    THINPROVISION = True
    SRNAME = "lvmohba-thin"
    
class TCThinLVHDSRProtection(_ThinLVHDBase):
    """ Verify protection when master is down. """

    DEFAULTVDISIZE = 10*xenrt.GIGA

    def checkVdiWrite(self, guest, device = None, size=xenrt.GIGA):
        try:
            self.fillDisk(guest, size=size, targetDir=device)
        except Exception, e:
                log("Not able to write in to device %s on the guest %s : failed with exception %s: " % (device, guest, str(e)))
                return False
        return True

    def prepare(self, arglist):
        args  = self.parseArgsKeyValue(arglist)
        self.pool = self.getDefaultPool()
        self.master = self.pool.master
        self.slave = self.pool.getSlaves()[0]
        self.backupMaster = self.pool.getSlaves()[1]
        self.sruuid = self.pool.getPoolParam("default-SR")
        self.vdisize = int(args.get("vdisize", self.DEFAULTVDISIZE))
        vmonlocalsr = bool(args.get("vmonlocalsr", False))
        if vmonlocalsr:
            localsruuid = self.slave.getLocalSR()
            self.guest = self.slave.createBasicGuest("generic-linux", sr=localsruuid)
        else:
            self.guest = self.slave.createBasicGuest("generic-linux", sr=self.sruuid)

    def run(self, arglist):
        step("Creating a virtual disk and attaching to VM...")
        device = self.guest.createDisk(sizebytes=self.vdisize, returnDevice=True)
        step("Shutting down the pool master ...")
        self.master.machine.powerctl.off()
        xenrt.sleep(180)
        step("Verify that we can write minimum 1GiB of data onto the guest when pool master is down") 
        if not self.checkVdiWrite(self.guest, device):
            raise xenrt.XRTFailure("Not able to write minimum 1 GiB of data onto the guest %s when the pool master is down" % (self.guest))
        step("Verify that we not able to write more than 3GiB of data onto the guest when the pool master is down")
        if self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Able to write more than 3 GiB of data onto the guest %s when the pool master is down" % (self.guest))
        step("Bringing the pool master Up again...")
        self.master.machine.powerctl.on() 
        # Wait for it to boot up
        self.master.waitForSSH(900)
        step("Verify that we can write more than 3 GiB of data onto the guest %s when the pool master is up" % (self.guest))
        if not self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Not able to write more than 3 GiB of data onto the guest %s when the pool master is up" % (self.guest))
        step("Eject the master from the pool ...")
        self.master.machine.powerctl.off()
        xenrt.sleep(15)
        self.pool.setMaster(self.backupMaster)
        self.pool.recoverSlaves()
        self.pool.eject(self.master)
        step("Verify that we can write more than 3 GiB of data onto the guest %s with the new pool master" % (self.guest))
        if not self.checkVdiWrite(self.guest, device, size=3*xenrt.GIGA):
            raise xenrt.XRTFailure("Not able to write more than 3 GiB onto the guest %s after elect a new pool master" % (self.DEFAULTMAXDATA))

    def postRun(self):
        self.master.machine.powerctl.on() 
        # Wait for it to boot up
        self.master.waitForSSH(900)

class TCThinLVHDVmOpsSpace(_ThinLVHDBase):
    """verify suspended/snapshot VDIs take space properly"""

    DEFAULTSRTYPE = "lvmoiscsi"
    GUESTMEMORY = 8192 # in MiB

    def checkVDIInitialAlloc(self, vdiuuid, expectedVdiSize):
        initialalloc = self.getInitialAllocation(vdiuuid)
        if initialalloc < expectedVdiSize:
            raise xenrt.XRTFailure("VDI initial allocation is not as expected. (Expected >= %s, found: %s)" %
                    (expectedVdiSize, initialalloc))

    # TODO: This needs to be checked while checkpoint/suspend is on going.
    # After task is done, they are inflated any way.
    #def checkVDIPhysicalSize(self, vdiuuid, expectedVdiSize):
    #    vdiPhysicalSize = self.getPhysicalVDISize(vdiuuid)
    #    if vdiPhysicalSize < expectedVdiSize:
    #        raise xenrt.XRTFailure("VDI Physical size not as expected. Expected at least %s bytes but found %s bytes" %
    #                              (expectedVdiSize, vdiPhysicalSize))


    def checkSRPhysicalUtil(self, expectedphysicalUtil):
        step("Checking the SR physical utilization. Expected SR physical utilization is %s bytes..." % (expectedphysicalUtil))
        srPhysicalUtil = self.getPhysicalUtilisation(self.sr)
        if srPhysicalUtil < expectedphysicalUtil:
            raise xenrt.XRTFailure("SR physical utilization not as expected. Expected at least %s bytes but found %s bytes" %
                                  (expectedphysicalUtil, srPhysicalUtil))

    def checkSRPhysicalUtil2(self, expectedphysicalUtil):
        step("Checking the SR physical utilization. Expected SR physical utilization is %s bytes..." % (expectedphysicalUtil))
        srPhysicalUtil = self.getPhysicalUtilisation(self.sr)
        if srPhysicalUtil > expectedphysicalUtil:
            raise xenrt.XRTFailure("SR physical utilization not as expected. Expected at max %s bytes but found %s bytes" %
                                  (expectedphysicalUtil, srPhysicalUtil))

    def performVmOps(self):
        """ This function check's that checkpoint/suspend operation on thin-provisioned SR works as expected"""

        self.phyUtilBeforeCheckpoint = self.getPhysicalUtilisation(self.sr) + self.guestMemory
        step("Taking the vm checkpoint...")
        self.checkuuid = self.guest.checkpoint()
        vdiUuid = self.host.genParamGet("vm", self.checkuuid, "suspend-VDI-uuid")
        step("check SR Physical utilization...")
        self.checkSRPhysicalUtil(self.phyUtilBeforeCheckpoint)
        # TODO: This needs to be checked while checkpoint is on going.
        #step("Test that VDI created after checkpoint is thick provisioned by checking the size...")
        #self.checkVDIPhysicalSize(vdiUuid, self.guestMemory)
        step("Check initial allocation of suspended VDI. This should be bigger than guest memory size.")
        self.checkVDIInitialAlloc(vdiUuid, self.guestMemory)

        expectedphysicalUtil = self.getPhysicalUtilisation(self.sr) + self.guestMemory
        step("Suspending the VM...")
        self.guest.suspend()
        suspendVdiUuid = self.guest.paramGet("suspend-VDI-uuid")
        step("check SR Physical utilization...")
        self.checkSRPhysicalUtil(expectedphysicalUtil)
        # TODO: This needs to be checked while suspend is on going.
        #step("Test that VDI created after suspend is thick provisioned by measuring the size...")
        #self.checkVDIPhysicalSize(suspendVdiUuid, self.guestMemory) 
        step("Check initial allocation of suspended VDI. This should be bigger than guest memory size.")
        self.checkVDIInitialAlloc(suspendVdiUuid, self.guestMemory)

    def revertVmOps(self):
        """This function check's that resume/revert on thin-provision SR works as expected"""
        if self.guest.getState() == "SUSPENDED":
            expectedphysicalUtil = self.getPhysicalUtilisation(self.sr) - self.guestMemory
            step("Resuming the VM...")
            self.guest.resume()
            self.guest.check()
            self.checkSRPhysicalUtil2(expectedphysicalUtil)
        if self.checkuuid:
            step("Reverting the checkpoint...")
            self.guest.revert(self.checkuuid)
            self.guest.check()
            self.checkSRPhysicalUtil2(self.phyUtilBeforeCheckpoint)

    def prepare(self, arglist=[]):
        args = self.parseArgsKeyValue(arglist)
        self.host = self.getDefaultHost()
        self.srtype = args.get("srtype", self.DEFAULTSRTYPE)
        self.guestMemory = int(args.get("guestmemory", self.GUESTMEMORY))
        self.checkuuid = None
        srs = self.getThinProvisioningSRs()
        if not srs:
            step("Creating thin provisioned SR of type %s" %(self.srtype))
            self.sr = self.createThinSR(host=self.host, size=200, srtype=self.srtype)
        else:
            self.sr = srs[0]
        if "guest" in args:
            self.guest = self.getGuest(args["guest"]) 
            self.guest.setState("UP")
        else:
            self.guestMemory = int(args.get("guestmemory", self.GUESTMEMORY))
            self.guest = self.host.createBasicGuest("generic-linux", sr=self.sr.uuid, memory=self.guestMemory)
        log("setting up the SR %s as a default SR of the host" % (self.srtype))
        self.host.addSR(self.sr, default=True)
        self.guestMemory = self.guestMemory * xenrt.MEGA
        log("Guest memory reported %s bytes" % (self.guestMemory))

    def run(self, arglist=[]):

        # Test that snapshot/suspend works as expected on thin-provisioned SR.
        if self.runSubcase("performVmOps", (), "vmops-snapshot/suspend", "Guest Memory=%s bytes"\
                            %(self.guestMemory))== xenrt.RESULT_PASS:
            # Test that resume/revert works as expected on thin-provisioned SR
            self.runSubcase("revertVmOps", (), "vmops-resume/revert", "Guest Memory=%s bytes" % (self.guestMemory))


class TCConcurrentAccess(_ThinLVHDBase):
    """Concurrent access to the shared thin storage from multiple hosts in a pool of hosts"""

    def attachDisks(self, readOnly=False):
        """Attach VDIs onto each guests."""
        for guest in self.guests:
            self.guests[guest]['device'] = guest.createDisk(vdiuuid=self.guests[guest]["vdi"],
                    returnDevice=True, mode="RO" if readOnly else "RW")

    def detachDisks(self):
        """Destroy all VBDs"""
        cli = self.host.getCLIInstance()
        for guest in self.guests:
            vbd = self.host.minimalList("vbd-list", None, "vdi-uuid=%s" % self.guests[guest]["vdi"])[0]
            cli.execute("vbd-unplug", "uuid=%s" % (vbd))
            cli.execute("vbd-destroy", "uuid=%s" % (vbd))

    def readDisk(self, guest, device):
        """Attach VDI as RO and try read."""

        return guest.execguest("dd if=/dev/%s of=/dev/null bs=1M" % device, retval="code")

    def writeDisk(self, guest, device, size):
        """Fill disk with"""

        return guest.execguest("dd if=/dev/zero of=/dev/%s bs=1M count=%d" % (device, size * xenrt.KILO), retval="code")
        # size in GiB, count * bs = size. KILO = GIGA / MEGA
        
    def testConcurrentAccess(self, read=False):
        """Subcase testing concurrent access to multiple read-only VDIs from multiple hosts in a single pool."""

        step("Attach all VIDs onto guests %s" % "read only" if read else "")
        self.attachDisks(readOnly=read)


        step("%s disk concurrently" % "read from" if read else "write")
        tasks = []
        for guest in self.guests:
            if read:
                tasks.append(xenrt.PTask(self.readDisk, guest, self.guests[guest]["device"]))
            else:
                tasks.append(xenrt.PTask(self.writeDisk, guest, self.guests[guest]["device"], self.vdisize))
                
        results = xenrt.pfarm(tasks, exception=False)

        failed = 0
        for res in results:
            if res and res != "0":
                warning("Found exception: %s" % res)
                failed += 1

        step("Detaching all VDIs")
        self.detachDisks()

        if failed:
            raise xenrt.XRTFailure("%d / %d %s task(s) failed." %
                    (failed, self.vdicount, "reading" if read else "writing"))

    def prepare(self, arglist=[]):

        log("Obtaining test environment.")
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        if not self.pool:
            raise xenrt.XRTError("This test requires a pool.")
        self.hosts = self.pool.getHosts()
        hostcount = len(self.hosts)

        log("Searching for target thin LVHD.")
        self.srs = self.getThinProvisioningSRs()
        if not self.srs:
            raise xenrt.XRTError("No thin provisioning SR found.")
        self.sr = self.srs[0]
        log("Found SR: %s (%s)" % (self.sr.uuid, self.sr.srtype))

        log("Read env vars")
        args = self.parseArgsKeyValue(arglist)
        self.vdicount = int(args.get("vdicount", hostcount))
        self.vdisize = int(args.get("vdisize", "2")) # in GiB
        log("Using %d vdis, %d GiB each for %d hosts" % (self.vdicount, self.vdisize, hostcount))

        log("Creating %d VMs" % self.vdicount)
        master = self.getGuest("lingold")
        if not master:
            raise xenrt.XRTError("Failed to obtain master guest lingold")
        master.setState("DOWN")
        self.guests = {}
        for i in xrange(self.vdicount):
            guest = master.cloneVM(name="testvm_%d" % i)
            guest.setHost(self.hosts[i % hostcount])
            guest.setState("UP")
            vdi = self.host.createVDI(self.vdisize * xenrt.GIGA, name="testdisk_%d" % i)
            self.uninstallOnCleanup(guest)

            self.guests[guest] = {'vdi': vdi}

    def run(self, arglist):

        self.runSubcase("testConcurrentAccess", (), "writing", "RW")
        self.runSubcase("testConcurrentAccess", (True), "reading", "RO")

    def postRun(self):

        cli = self.host.getCLIInstance()
        for guest in self.guests:
            try:
                cli.execute("vdi-destroy", "uuid=%s" % self.guests[guest]["vdi"])
            except:
                pass


class XRTSRUpgradeFail(xenrt.XRTError):
    """An error class to handle lvhd-enable-thin-provisioning cli command error."""
    pass


class TCSRUpgrade(_ThinLVHDBase):
    """Test the SR upgrade process from thick provisioned to thin provisioned"""

    OUTPUT_PATH = "/tmp/srupgradeoutput"
    UPGRADE_TIMEOUT = "5" # in minutes.

    def getDigest(self, guest, device="/dev/xvdb"):
        """Return md5 string"""

        return guest.execguest("md5sum %s" % device).split()[0]
        
    def runSRUpgrade(self, sruuid, initialAlloc=None, quantumAlloc=None, async=False):
        """Invoke SR upgrade"""

        args = []
        args.append("sr-uuid=%s" % (sruuid))
        if initialAlloc:
            args.append("initial_allocation=%s" % (initialAlloc))
        if quantumAlloc:
            args.append("quantum_allocation=%s" % (quantumAlloc))

        cmd = "lvhd-enable-thin-provisioning %s > %s 2>&1" % (" ".join(args), self.OUTPUT_PATH)

        if async:
            cmd += " < /dev/null &"

        cli = self.host.getCLIInstance()
        ret = cli.execute(cmd, retval="code")

        if async:
            return ret

        output = self.grabSRUpgradeOutput()
        if ret:
            raise XRTSRUpgradeFail("SR upgrade command returned error: %s" % output)

        return output

    def grabSRUpgradeOutput(self):
        """obtain output of SR upgrade."""
        d = "%s/srupgrade-output" % (xenrt.TEC().getLogdir())
        try:
            sftp = self.host.sftpClient()
            sftp.copyFrom(self.OUTPUT_PATH, d)
        except Exception, e:
            warning("Failed to obtain output: %s" % self.OUTPUT_PATH)
            return ""
        with open(d, "r") as out:
            return out.read()

    def checkSRUpgradeProcess(self):
        """Check whether SR upgrad process is running"""

        return not self.host.execdom0("ps -efl | grep '[l]vhd-enable-thin-provisioning'", retval="code")

    def getSRObjByType(self, srtype):
        """Search SRs by sr type"""

        host = self.host
        if not host:
            host = self.getDefaultHost()

        xsrs = [sr for sr in host.asXapiObject().SR(False) if sr.srType() == srtype]
        if not xsrs:
            raise xenrt.XRTError("Cannot find %s type SR." % srtype)

        for xsr in xsrs:
            sr = xenrt.lib.xenserver.getStorageRepositoryClass(host, xsr.uuid).fromExistingSR(host, xsr.uuid)
            if not sr.thinProvisioning:
                return sr

        raise xenrt.XRTError("All found SRs of %s type are already thin provisioned." % srtype)

    def prepare(self, arglist=[]):

        step("Setting up testing env before SR upgrade.")
        args = self.parseArgsKeyValue(arglist)

        self.host = self.getDefaultHost()
        self.upgradetimeout = int(args.get("srupgradetime", self.UPGRADE_TIMEOUT)) # in minutes.

        srtype = args.get("srtype", "lvmoiscsi")
        self.sr = self.getSRObjByType(srtype)
        log("Found none thin provisioning %s SR: %s" % (srtype, self.sr.uuid))

        log("Setting up master guest.")
        baseimage = args.get("baseimagename", None)
        self.master = self.getGuest(baseimage)
        if not self.master:
            raise xenrt.XRTError("Could not find the base image %s." % baseimage)

        self.guests = {}
        self.guests[self.master] = {}

        log("Creating an additional disk of size 2GiB and attach to VM")
        vdiuuid = self.host.createVDI(2 * xenrt.GIGA, name="extra-disk")
        userDevice = self.master.createDisk(vdiuuid=vdiuuid, returnDevice=True)
        self.guests[self.master]["device"] = userDevice

        step("Recording the extra disk checksum of the master VM before the snapshot")
        self.guests[self.master]["initial"] = self.getDigest(self.master, "/dev/" + userDevice)

        step("Take a snapshot of master VM")
        self.guests[self.master]["snapshot"] = self.master.snapshot()

        step("Writing a GiB of random data to the additional disk")
        self.fillDisk(self.master, targetDir="/dev/" + userDevice, size=xenrt.GIGA, source="/dev/urandom")
        self.guests[self.master]["afterWriting"] = self.getDigest(self.master, "/dev/" + userDevice)

        step("Shutting down master VM")
        self.master.shutdown()
        step("Cloning the master VM")
        self.clonedVM = self.master.cloneVM(name="cloned")
        step("Again copying the master VM")
        self.copiedVM = self.master.copyVM(name="copied")

        self.guests[self.clonedVM] = {"device": userDevice}
        self.guests[self.copiedVM] = {"device": userDevice}

        step("Distribute guests and starting VMs.")
        pool = self.getDefaultPool()
        if pool:
            self.master.setHost(pool.master)
            self.clonedVM.setHost(pool.getSlaves()[0])
            self.copiedVM.setHost(pool.getSlaves()[-1])
        for guest in self.guests:
            guest.start()

        step("Writing additional 1GiB of random data to extra disk of the cloned VM")
        self.fillDisk(self.clonedVM, targetDir="/dev/" + userDevice, size=2*xenrt.GIGA, source="/dev/urandom")
        self.guests[self.clonedVM]["afterWriting"] = self.getDigest(self.clonedVM, "/dev/" + userDevice)

        step("Writing additional 1GiB of random data to extra disk of the copied VM")
        self.fillDisk(self.copiedVM, targetDir="/dev/" + userDevice, size=2*xenrt.GIGA, source="/dev/urandom")
        self.guests[self.copiedVM]["afterWriting"] = self.getDigest(self.copiedVM, "/dev/" + userDevice)

        step("Shutting down the cloned VM")
        self.clonedVM.shutdown()
        step("Set reset-on-boot additional disk of the cloned VM")
        self.resetOnBootVDI = self.host.minimalList("vbd-list", args="vm-uuid=%s userdevice=1" % 
                                                self.clonedVM.getUUID(), params="vdi-uuid")[0]
        self.host.genParamSet("vdi", self.resetOnBootVDI, "on-boot", "reset")
        step("Starting cloned VM")
        self.clonedVM.start()

        step("Suspending the master VM")
        self.master.suspend()

        log("Give some time to settle down all SR changes.")
        xenrt.sleep(60)

    def rollBackTest(self):
        
        cli = self.host.getCLIInstance()

        step("Creating a VDI of remaining size of SR")
        pSize = self.getPhysicalSize(self.sr)
        left = pSize - self.getPhysicalUtilisation(self.sr)
        block = 32 * xenrt.MEGA # VDI will be create by size of block
        left =  left / block * block - block # VHD will require size of block for metadata and header
        vdiuuid = self.host.createVDI(left, name="remaining-disk")

        step("Verifying free space of SR is smaller than 0.5% * num of host of SR size or 1GiB, whichever smaller")
        left = pSize - self.getPhysicalUtilisation(self.sr)
        if left > min(0.05 * pSize * len(self.getAllHosts()), xenrt.GIGA): # Assumes all hosts are in the same pool.
            cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))
            raise xenrt.XRTError("Failed to create failover case.")

        step("Trying SR upgrade.")
        try:
            self.runSRUpgrade(self.sr.uuid)
        except XRTSRUpgradeFail as e:
            log("SR upgrade failed as expected. output: %s" % e)
        else:
            raise xenrt.XRTFailure("SR upgrade succeded with small free space. sr size: %d, sr free space: %d" %
                    (pSize, left))
        finally:
            cli.execute("vdi-destroy", "uuid=%s" % (vdiuuid))

        step("Checking roll-backed properly.")
        self.host.check()
        for guest in [self.clonedVM, self.copiedVM]: # master is suspended hence not checkable.
            if self.guests[guest]["afterWriting"] != self.getDigest(guest, "/dev/" + self.guests[guest]["device"]):
                raise xenrt.XRTFailure("%s of %s is not rolled back properly" % (self.guests[guest]["device"], guest.getName()))
        
    def srUpgradeTest(self):

        cli = self.host.getCLIInstance()

        step("Starting to upgrade the SR to thin provisioned SR")
        self.runSRUpgrade(self.sr.uuid, async=True)
        starttime = xenrt.timenow()

        if not self.checkSRUpgradeProcess():
            raise xenrt.XRTFailure("SR Upgrade failed to run.")

        xenrt.TEC().logverbose("The operations will be progressing parellely."
                                    "We will wait for for all the operations to complete")

        step("Running IO ops")
        pDirTasks = [xenrt.PTask(self.copiedVM.execguest, "dd if=/dev/zero of=/tmp/delete_me bs=1M count=10", retval="code"), # ---> this should succeed.
                  xenrt.PTask(self.clonedVM.execguest, "dd if=/dev/zero of=/tmp/delete_me bs=1M count=10", retval="code"), # ---> this should succeed.
                  xenrt.PTask(self.copiedVM.execguest, "ls / && ls /home", retval="code"), # ---> this should succeed.
                  xenrt.PTask(self.clonedVM.execguest, "ls / && ls /home", retval="code")] # ---> this should succeed.
        ioresults = xenrt.pfarm(pDirTasks, exception=False)
        log("IO ops results: %s" % ioresults)

        step("Running VM ops")
        pOpTasks = [xenrt.PTask(self.copiedVM.reboot), # ---> this should succeed.
                    xenrt.PTask(self.clonedVM.snapshot)] # ---> this should fail.
        opsresults = xenrt.pfarm(pOpTasks, exception=False)
        log("VM ops results: %s" % opsresults)

        failed = 0
        for result in ioresults + opsresults:
            if result:
                failed += 1
        if failed < 1:
            raise xenrt.XRTFailure("Task(s) should fail succeeded.")
        if failed > 1:
            raise xenrt.XRTFailure("Task(s) should succeed failed.")
            
        step("Wait until SR upgrade finishes.")
        while xenrt.timenow() - starttime < self.upgradetimeout * 60:
            if not self.checkSRUpgradeProcess():
                break
            xenrt.sleep(30, log=False)
        else:
            raise xenrt.XRTFailure("SR upgrade took more than %d minutes." % self.srupgradetimeout)

        step("Checking if the SR upgrade is succeeded as expected")
        output = self.grabSRUpgradeOutput()
        log("SR upgrade output: %s" % output)
        if "error" in output.lower() or "exception" in output.lower():
            raise xenrt.XRTFailure("Error(s) found from SR upgrade output.")

        # After upgrade is done, check status of SR.
        step("Checking Status of host and SR")
        self.host.check()
        if not self.isThinProvisioning(self.sr):
            raise xenrt.XRTFailure("The SR %s is not upgraded to thin provisioned" % (self.sr.srtype))

        step("Checking the physical size of all converted VDI after SR upgrade.")
        for guest in self.guests:
            vdi = self.host.minimalList("vbd-list", args="vm-uuid=%s userdevice=1" % 
                    guest.getUUID(), params="vdi-uuid")[0]
            if self.getPhysicalVDISize(vdi, self.host) <= 2 * xenrt.GIGA:
                raise xenrt.XRTFailure("VDI has been shrinked after SR upgrade.")

        step("Resuming suspended VM")
        self.master.resume()

        step("Checking content of VDIs not changed.")
        for guest in self.guests:
            if self.guests[guest]["afterWriting"] != self.getDigest(guest, "/dev/" + self.guests[guest]["device"]):
                raise xenrt.XRTFailure("%s of %s is changed after SR upgrade." % (self.guests[guest]["device"], guest.getName()))

        step("Checking reset-on-boot is set as expected on cloned VM. Only cloned VM extra disk should be reset")
        if self.host.genParamGet("vdi", self.resetOnBootVDI, "on-boot") != "reset":
            raise xenrt.XRTFailure("Reset-on-boot param is changed after the SR upgrade.")

        step("Reverting the master snapshot")
        cli.execute("snapshot-revert snapshot-uuid=%s" % self.guests[self.master]["snapshot"])

        step("Checking contents of VDI is reverted properly.")
        if self.guests[self.master]["initial"] != self.getDigest(guest, "/dev/" + self.guests[self.master]["device"]):
            raise xenrt.XRTFailure("Contents of snapshot is changed after SR upgrade.")

        step("Creating a new VDI and check its initial allocation")
        vdi = self.host.createVDI(xenrt.GIGA)
        # Newly created VDI should have allocated as initial allocation 
        # Allow 5% margin and 50MiB if initial allocation is 0 (or clese to 0)
        initial = self.getInitialAllocation(self.sr)
        quantum = self.getAllocationQuantum(self.sr)
        allocated = self.getPhysicalVDISize(vdi)
        if allocated > max(initial * 1.05, 50 * xenrt.MEGA):
            raise xenrt.XRTFailure("Newly created VDI is allocated more than initial allocation."
                    "Expected: %d, allocated: %d" % (initial, allocated))
        device = self.master.createDisk(vdiuuid=vdi, returnDevice=True)
        expected = initial + quantum * 10
        self.fillDisk(self.master, targetDir="/dev/" + device, size=expected)
        allocated = self.getPhysicalVDISize(vdi)
        if allocated < expected or allocated > expected * 1.05:
            raise xenrt.XRTFailure("Size of VDI is not increased as expected. Expected: %d, Allocated: %d" %
                    (expected, allocated))
            
    def run(self, arglist=[]):

        self.runSubcase("rollBackTest", (), "SRUpgrade", "roll back")
        self.runSubcase("srUpgradeTest", (), "SRUpgrade", "SR upgrade")
