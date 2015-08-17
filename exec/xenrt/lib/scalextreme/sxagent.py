import xenrt
from xenrt.ssh import SSH
from xenrt.lib.scalextreme.sxapi import SXAPI

__all__ = [ "SXAgent" ]

class SXAgent(object):
    """ A object that represent SX gateway"""
    AGENT_VM_ID = "root"
    AGENT_VM_PWD = "xenroot"

    def __init__(self):
        super(SXAgent, self).__init__()

        self.__agentVM = None
        self.__apikey = xenrt.TEC().lookup("SXA_APIKEY", None)
        self.__credential = xenrt.TEC().lookup("SXA_CREDENTIAL", None)
        self.__nodeid = None
        self.__api = None

    def __getAgentURL(self):
        """Get the URL to download agent using Rest API"""
        info = self.apiHandler.execute(category="download", command="info")
        if not "data" in info or not "deb64" in info["data"]:
            raise xenrt.XRTError("Cannot retrieve download URL.")

        url = info["data"]["deb64"].replace("\\", "")
        # Rest API returns a url that requires authentication.
        # Using url from web interface.
        # Todo: Check with SX whether this is expected.
        return url.replace("https://lifecycle.cloud.com/store", "https://manage-mon.citrix.com")

    def __executeOnAgent(self, command):
        """Execute a command on agent Linux VM via SSH"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")

        return SSH(self.agentIP, command, timeout=120, password=self.AGENT_VM_PWD)

    @property
    def agentVM(self):
        """The Guest object of agent VM"""
        return self.__agentVM

    @agentVM.setter
    def agentVM(self, vm):
        self.__agentVM = vm

    @property
    def apiKey(self):
        """API Key that is passed from sequene file."""
        return self.__apikey

    @apiKey.setter
    def apiKey(self, key):
        self.__apikey = key

    @property
    def credential(self):
        """Client credential for authenticate."""
        return self.__credential

    @credential.setter
    def credential(self, cred):
        self.__credential = cred

    @property
    def nodeId(self):
        """Node ID. -Read only-"""
        return self.__nodeid

    @property
    def apiHandler(self):
        """Rest API handler. -Read only-"""
        if not self.__api:
           self.__api = SXAPI(self.apiKey, self.credential)
        return self.__api

    @property
    def agentIP(self):
        """The IP of agent VM. -Read only-"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")
        return self.__agentVM.getIP()

    def installAgent(self):
        """Install agent on vm"""
        if not self.__agentVM:
            raise xenrt.XRTError("Agent VM is not assigned.")

        self.__agentVM.setState("UP")

        url = self.__getAgentURL()
        try:
            self.__executeOnAgent("wget %s -O agent.deb" % url)
            self.__executeOnAgent("dpkg -i agent.deb")
        except:
            # SSH command failure can be ignored.
            # installation will be verified in code below.
            pass

        # Give some time to ScaleXtremem to get connected to this agent.
        xenrt.sleep(30)

        nodes = self.apiHandler.execute(category="nodes")
        nodeid = None
        for node in nodes:
            for attr in node["nodeAttrList"]:
                if attr["attributeName"] == "ip" and attr["attributeValue"] == self.agentIP:
                    nodeid = node["nodeId"]
                    break
            else:
                continue
            break

        if nodeid == None:
            raise xenrt.XRTError("Cannot find node of agent installed. Is it installed and running?")
        self.__nodeid = nodeid

    def setAsGateway(self):
        """Set this agent VM as gateway to XenServer"""

        if self.nodeId == None:
            raise xenrt.XRTException("Node Id is not set. Is agent installed properly?")

        r = self.apiHandler.execute(method="PUT", category="nodes", sid=str(self.nodeId), command="setasgateway")

        if "result" in r and r["result"] == "SUCCESS":
            return True

        return False

    def createEnvironment(self, host=None):
        """Create environment with existing agent and XenServer"""

        if self.nodeId == None:
            raise xenrt.XRTException("Node Id is not set. Is agent installed properly?")

        if not host:
            host = self.agentVM.host

        self.apiHandler.execute(method="POST", category="providers",
            params = {"name": xenrt.TEC().lookup("SX_ENVIRONMENT_NAME", "xenrt-%s" % xenrt.TEC().lookup("JOBID", "nojob")),
                "providercode": "xenserver",
                "server": "http://" + host.getIP(),
                "username": "root",
                "password": "xenroot",
                "agentId": str(self.nodeId)
            }
        )

