# Test harness for Xen and the XenServer product family
#
# RDP verification tests on the linux and windows guests
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

import xenrt
from xenrt.lazylog import step
from xenrt.lib.xenserver.xapirdp import XapiRdp

class TC23790(xenrt.TestCase):
    """ Verify that XAPI can switch RDP for windows guests with fresh installed tools."""

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guestlist = self.getGuest(self.args['guestlist']).split(",")

    def run(self, arglist=None):
        for self.guest in self.guestlist:
            self.uninstallOnCleanup(self.guest)
            xapiRdpObj = XapiRdp(self.guest)

            # Check that RDP is disabled on the guest with no tools installed
            if xapiRdpObj.isRdpEnabled():
                raise xenrt.XRTFailure("RDP is enabled on the guest: %s with no tools %s ." % (self.guest))
            xenrt.TEC().logverbose("RDP is currently diabled on the guest %s" % (self.guest))

            # Check that XAPI can not switch RDP with no tools installed
            if not xapiRdpObj.enableRdp():
                raise xenrt.XRTFailure("XAPI enabled the RDP for the guest %s with no tools." % (self.guest))
            xenrt.TEC().logverbose("XAPI couldn't enabled RDP for the guest %s with no tools" % (self.guest))

            #Install tools 
            step("Installing the latest driver tools on the guest")
            self.guest.installDrivers()
            self.guest.waitForAgent(180)
            self.guest.reboot()
            self.guest.check()

            # Check that XAPI can switch RDP with tools installed
            if xapiRdpObj.enableRdp():
                raise xenrt.XRTFailure("XAPI failed to enable the RDP on the guest %s with tools installed " % (self.guest))
            xenrt.TEC().logverbose("XAPI successfully enabled the RDP for the guest: %s " % (self.guest))
    
            # win_guest_agent takes at max 10 seconds to update RDP status to data/ts
            xenrt.sleep(10)

            # Ensure that data/ts updated with latest RDP status
            if not xapiRdpObj.isRdpEnabled():
                raise xenrt.XRTFailure("Guest agent does not updated  data/ts about the RDP status change for the guest %s " % (self.guest))
            xenrt.TEC().logverbose("Guest agent updated the RDP status in data/ts successfully for the guest %s" % (self.guest))

class TC23791(xenrt.TestCase):
    """ Verify that XAPI cannot switch RDP for linux guests """

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):

        # Verify that XAPI cannot switch RDP 
        xapiRdpObj = XapiRdp(self.guest)
        if not xapiRdpObj.enableRdp():
            raise xenrt.XRTFailure("XAPI switched the RDP for the linux guest %s." % (self.guest))
        xenrt.TEC().logverbose("XAPI couldn't switch the RDP for the linux guest: %s " % (self.guest))

        self.guest.checkHealth()

class TC23792(xenrt.TestCase):
    """Verify that RDP settings on the windows guests are made after XAPI enable/disable RDP"""

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        xapiRdpObj = XapiRdp(self.guest)

        # Disable the RDP on the guest
        step(" Test is trying to set fDenyTSConnections on the guest to disable RDP")
        self.guest.winRegAdd('HKLM', 'System\\CurrentControlSet\\Control\\Terminal Server\\', 'fDenyTSConnections',"DWORD", 1)

        # Disable the RDP services in firewall by adding firewall rule 
        group="remote desktop"
        cmd="netsh advfirewall firewall set rule group=\"%s\" new enable=No" %(group)
        self.guest.xmlrpcExec(cmd)

        # Enable RDP via XAPI
        if xapiRdpObj.enableRdp():
            raise xenrt.XRTFailure("XAPI failed to enable the RDP on the guest with tools installed %s ." % (self.guest))
        xenrt.TEC().logverbose("XAPI successfully enabled the RDP for the guest: %s " % (self.guest))

        step("Check that fDenyTSConnections on the guest is reset after XAPI enabled RDP")
        # Check RDP settings : Check fDenyTSConnections
        fDenyTSConnections=self.guest.winRegLookup('HKLM', 'System\\CurrentControlSet\\Control\\Terminal Server\\', 'fDenyTSConnections',
                                                   healthCheckOnFailure=False)

        if fDenyTSConnections:
            raise xenrt.XRTFailure("fDenyTSConnections on the guest %s not reverted to 0" % (self.guest))
        xenrt.TEC().logverbose("fDenyTSConnections on the guest %s is reverted to 0" % (self.guest))

        #TODO:  Code to check firewall rule for RDP : Do we need ? 

        if xapiRdpObj.disableRdp():
            raise xenrt.XRTFailure("XAPI failed to disable the RDP on the guest with tools installed %s ." % (self.guest))
        xenrt.TEC().logverbose("XAPI successfully disabled the RDP for the guest: %s " % (self.guest))

        # Check RDP settings : Check fDenyTSConnections
        step("Check that fDenyTSConnections on the guest is reset after XAPI disabled RDP")
        fDenyTSConnections=self.guest.winRegLookup('HKLM', 'System\\CurrentControlSet\\Control\\Terminal Server\\', 'fDenyTSConnections',
                                                   healthCheckOnFailure=False)

        if not fDenyTSConnections:
            raise xenrt.XRTFailure("fDenyTSConnections on the guest %s not reverted to 1." % (self.guest))
        xenrt.TEC().logverbose("fDenyTSConnections on the guest %s reverted to 1" % (self.guest))

        # TODO:Code to check the firewall rule for RDP . Do we need ?

        self.guest.checkHealth()

class TC23793(xenrt.TestCase):
    """Verify that Manually disabling the RDP on the guest updates RDP disabled field in XAPI"""

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        # Install old tools 
        xapiRdpObj = XapiRdp(self.guest)

        # Enable RDP on the guest 
        if xapiRdpObj.enableRdp():
            raise xenrt.XRTFailure("XAPI failed to enable the RDP on the guest %s with tools installed" % (self.guest))
        xenrt.TEC().logverbose("XAPI successfully enabled the RDP for the guest: %s " % (self.guest))

        # win_guest_agent takes at max 10 seconds to update RDP status change to XAPI
        xenrt.sleep(10)
        if not xapiRdpObj.isRdpEnabled():
            raise xenrt.XRTFailure("Guest agent does not updated  data/ts about the RDP status change for the guest %s " % (self.guest))
        xenrt.TEC().logverbose("Guest agent updated the RDP status in data/ts successfully for the guest %s" % (self.guest))

        # Disable the RDP on the guest 
        step("Test trying to disable RDP on the guest by setting  windows registry key fDenyTSConnections to 1")
        self.guest.winRegAdd('HKLM', 'System\\CurrentControlSet\\Control\\Terminal Server\\', 'fDenyTSConnections',"DWORD", 1)
        xenrt.sleep(10)

        if xapiRdpObj.isRdpEnabled():
            raise xenrt.XRTFailure("Guest agent does not updated data/ts about the RDP status change for the guest %s " % (self.guest))
        xenrt.TEC().logverbose("Guest agent updated the RDP status in data/ts successfully for the guest %s" % (self.guest))

        self.guest.checkHealth()


class TC23794(xenrt.TestCase):
    """Test that post installation of tools collects the appropriate RDP settings."""

    def prepare(self, arglist=None):
        self.args  = self.parseArgsKeyValue(arglist)
        self.guest = self.getGuest(self.args['guest'])
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=None):
        xapiRdpObj = XapiRdp(self.guest)

         # Enable the RDP on the guest
        step(" Test is trying to enable the RDP on the guest by resetting fDenyTSConnections to 0")
        self.guest.winRegAdd('HKLM', 'System\\CurrentControlSet\\Control\\Terminal Server\\', 'fDenyTSConnections',"DWORD", 0)
        
        #Install tools 
        step("Installing the latest tools on the guest")
        self.guest.installDrivers()
        self.guest.waitForAgent(180)
        self.guest.reboot()
        self.guest.check()
        
        if not xapiRdpObj.isRdpEnabled():
            raise xenrt.XRTFailure("After tools installation previous RDP settings lost on the guest %s " % (self.guest))
        xenrt.TEC().logverbose("RDP settings made before new tools installation preserved on the guest %s" % (self.guest))
        

