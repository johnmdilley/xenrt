import xenrt, xenrt.lib.xenserver, time
from xenrt.lazylog import log, step

class XenTestRun(object):
    def __init__(self, host, name):
        self.host = host
        self.name = name

    def results(self):
        if 0 != self.host.execdom0("[ -e /var/log/xen/guest-%s.log ]" % self.name, retval="code"):
            raise xenrt.XRTFailure("/var/log/guest-%s.log does not exists." % self.name
)
        res = self.host.execdom0("grep -i 'Test Result:' /var/log/xen/guest-%s.log | tail -1 | awk -F: '{print $4}'" % self.name).strip()

        if res == "SUCCESS":
            xenrt.TEC().logverbose('Test %s Result: PASS' % self.name)
        else:
            raise xenrt.XRTFailure('Test %s Result: FAILED' % self.name)

    def run(self):
        self.host.execdom0("xl create /opt/xen-test-framework/%s.cfg" % self.name)
        time.sleep(10)
        self.results()

class TCRing0XenBase(xenrt.TestCase):
    def prepare(self, arglist):
        self.host = self.getDefaultHost()

        #install the xen-test-framework which is a prerequisite for running tests.
        step("install xen-test-framework RPM and copy other pre-requisites")

        moduleRpm = xenrt.TEC().getFile("/usr/groups/build/trunk-ring0/latest/binary-packages/RPMS/domain0/RPMS/x86_64/xen-test-framework-*.rpm")
        try:
            xenrt.checkFileExists(moduleRpm)
        except xenrt.XRTException, e:
            raise xenrt.XRTError(e.reason)

        modulePath = "/tmp/xen-test-framework.rpm"
        sh = self.host.sftpClient()
        try:
            sh.copyTo(moduleRpm, modulePath)
        finally:
            sh.close()

        self.host.execdom0("rpm --force -Uvh %s" % (modulePath))

        if 0 != self.host.execdom0("[ -e /etc/sysconfig/xencommons ]", retval="code"):
            raise xenrt.XRTFailure("/etc/sysconfig/xencommons does not exists.")

        self.host.execdom0("sed -i 's/#XENSTORED_TRACE.*/XENSTORED_TRACE=yes/' /etc/sysconfig/xencommons")
        self.host.execdom0("sed -i 's/#XENCONSOLED_TRACE.*/XENCONSOLED_TRACE=all/' /etc/sysconfig/xencommons")
        self.host.execdom0("/bin/systemctl restart xenconsoled.service")

class TCRing0XenPV32Test(TCRing0XenBase):
    def run(self, arglist):
        step("32bit PV test")
        xenPV32Test = XenTestRun(self.host, "test-pv32-example");
        xenPV32Test.run()

class TCRing0XenPV64Test(TCRing0XenBase):
    def run(self, arglist):
        step("64bit PV Test")
        xenPV64Test = XenTestRun(self.host, "test-pv64-example");
        xenPV64Test.run()

class TCRing0XenHVM32Test(TCRing0XenBase):
    def run(self, arglist):
        step("32bit HVM test")
        xenHvm32Test = XenTestRun(self.host, "test-hvm32-example");
        xenHvm32Test.run()

class TCRing0XenHVM64Test(TCRing0XenBase):
    def run(self, arglist):
        step("64bit HVM test")
        xenHvm64Test = XenTestRun(self.host, "test-hvm64-example");
        xenHvm64Test.run()
