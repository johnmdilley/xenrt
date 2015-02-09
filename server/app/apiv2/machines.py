from app.apiv2 import *
from pyramid.httpexceptions import *
import calendar
import app.utils
import json
import time
import jsonschema

class _MachineBase(XenRTAPIv2Page):

    def getMachineStatus(self,
                  status,
                  leaseuser,
                  pool):
        broken = pool.endswith("x")
        if leaseuser:
            return "leased"
        else:
            if status == "idle":
                return "broken" if broken else "idle"
            elif status in ("running", "scheduled", "slaved"):
                return "running"
            else:
                return "offline"

    def getMachines(self,
                    pools=[],
                    clusters=[],
                    resources=None,
                    sites=[],
                    status=[],
                    users=[],
                    machines=[],
                    flags=[],
                    limit=None,
                    offset=0,
                    pseudoHosts=False,
                    exceptionIfEmpty=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []

        if pools:
            conditions.append(self.generateInCondition("m.pool", pools))
            params.extend(pools)

        if clusters:
            conditions.append(self.generateInCondition("m.cluster", clusters))
            params.extend(clusters)

        if sites:
            conditions.append(self.generateInCondition("m.site", sites))
            params.extend(sites)

        if users:
            conditions.append(self.generateInCondition("m.comment", users))
            params.extend(users)

        if machines:
            conditions.append(self.generateInCondition("m.machine", machines))
            params.extend(machines)

        if status:
            statuscond = []
            for s in status:
                if s == "offline":
                    statuscond.append("(m.status not in ('idle', 'scheduled', 'running', 'slaved') AND m.comment IS NULL)")
                elif s == "idle":
                    statuscond.append("(m.status = 'idle' AND m.comment IS NULL AND right(m.pool, 1) != 'x')")
                elif s == "running":
                    statuscond.append("m.status in ('scheduled', 'running', 'slaved')")
                elif s == "broken":
                    statuscond.append("right(m.pool, 1) = 'x'")
                elif s == "leased":
                    statuscond.append("m.comment IS NOT NULL")
            if statuscond:
                conditions.append("(%s)" % " OR ".join(statuscond))

        if not pseudoHosts:
            conditions.append("m.machine != ('_' || s.site)")


        query = "SELECT m.machine, m.site, m.cluster, m.pool, m.status, m.resources, m.flags, m.comment, m.leaseto, m.leasereason, m.leasefrom, m.leasepolicy, s.flags, m.jobid FROM tblmachines m INNER JOIN tblsites s ON m.site=s.site"
        if conditions:
            query += " WHERE %s" % " AND ".join(conditions)

        cur.execute(query, self.expandVariables(params))

        ret = {}

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            machine = {
                "name": rc[0].strip(),
                "site": rc[1].strip(),
                "cluster": rc[2].strip(),
                "pool": rc[3].strip(),
                "rawstatus": rc[4].strip(),
                "status": self.getMachineStatus(rc[4].strip(), rc[7].strip() if rc[7] else None, rc[3].strip()),
                "flags": [],
                "resources": {},
                "leaseuser": rc[7].strip() if rc[7] else None,
                "leaseto": calendar.timegm(rc[8].timetuple()) if rc[8] else None,
                "leasereason": rc[9].strip() if rc[9] else None,
                "leasefrom": calendar.timegm(rc[10].timetuple()) if rc[10] else None,
                "leasepolicy": rc[11],
                "jobid": rc[13],
                "broken": rc[3].strip().endswith("x"),
                "params": {}
            }

            for r in rc[5].strip().split("/"):
                if not "=" in r:
                    continue
                (key, value) = r.split("=", 1)
                machine['resources'][key] = value
                

            siteflags = rc[12].strip().split(",") if rc[12].split(",") else []
            machine['flags'].extend(siteflags)

            ret[rc[0].strip()] = machine
        if len(ret.keys()) == 0:
            if exceptionIfEmpty:
                raise XenRTAPIError(HTTPNotFound, "Machine not found")

            return ret
        query = "SELECT machine, key, value FROM tblmachinedata WHERE %s" % self.generateInCondition("machine", ret.keys())
        cur.execute(query, ret.keys())

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            if rc[2] and rc[2].strip():
                ret[rc[0].strip()]["params"][rc[1].strip()] = rc[2].strip()
            if rc[1].strip() == "PROPS" and rc[2] and rc[2].strip():
                ret[rc[0].strip()]['flags'].extend(rc[2].strip().split(","))

        for m in ret.keys():
            if flags:
                if not app.utils.check_attributes(",".join(ret[m]['flags']), ",".join(flags)):
                    del ret[m]
                    continue
            if resources:
                if not app.utils.check_resources("/".join(ret[m]['resources']), "/".join(resources)):
                    del ret[m]
                    continue

        if limit:
            machinesToReturn = sorted(ret.keys())[offset:offset+limit]

            for m in ret.keys():
                if not m in machinesToReturn:
                    del ret[m]

        return ret

    def updateMachineField(self, machine, key, value, commit=True, allowReservedField=False):
        db = self.getDB()

        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        details = machines[machine]['params']
        if key.lower() in ("machine", "comment", "leaseto", "leasereason", "leasefrom"):
            raise XenRTAPIError(HTTPForbidden, "Can't update this field")
        if key.lower() in ("status", "jobid") and not allowReservedField:
            raise XenRTAPIError(HTTPForbidden, "Can't update this field")
        if key.lower() in ("site", "cluster", "pool", "status", "resources", "flags", "descr", "jobid", "leasepolicy"):
            cur = db.cursor()
            try:
                cur.execute("UPDATE tblmachines SET %s=%%s WHERE machine=%%s;" % (key.lower()), (value, machine))
                if commit:
                    db.commit()
            finally:
                cur.close()
        else:
            cur = db.cursor()
            try:
                if value == None or value == "":
                    # Use empty string as a way to delete a property
                    cur.execute("DELETE FROM tblmachinedata WHERE machine=%s "
                                "AND key=%s;", [machine, key])
                elif not details.has_key(key):
                    cur.execute("INSERT INTO tblmachinedata (machine,key,value) "
                                "VALUES (%s,%s,%s);", [machine, key, str(value)])
                else:
                    cur.execute("UPDATE tblmachinedata SET value=%s WHERE "
                                "machine=%s AND key=%s;", [str(value),machine,key])
                if commit:
                    db.commit()
            finally:
                cur.close()
    
    def return_machine(self, machine, user, force, canForce=True, commit=True):
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        leasedTo = machines[machine]['leaseuser']
        if not leasedTo:
            raise XenRTAPIError(HTTPPreconditionFailed, "Machine is not leased")
        elif leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is leased to %s" % leasedTo, canForce=canForce)
        
        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = NULL, comment = NULL, leasefrom = NULL, leasereason = NULL "
                    "WHERE machine = %s",
                    [machine])
        if commit:
            db.commit()
        cur.close()        

    def addMachine(self, name, site, pool, cluster, resources, description, commit=True):
        db = self.getDB()
        cur = db.cursor()
        try:
            query = "INSERT INTO tblmachines(machine, site, cluster, pool, status, resources, descr) VALUES (%s, %s, %s, %s, 'idle', %s, %s)"
            params = [name, site, pool, cluster, "/".join(["%s=%s" % (x,y) for (x,y) in resources.items()]), description]

            cur.execute(query, params)

            if commit:
                db.commit()
        finally:
            cur.close()

    def lease(self, machine, user, duration, reason, force):
        leaseFrom = time.strftime("%Y-%m-%d %H:%M:%S",
                                time.gmtime(time.time()))
        if duration:
            leaseToTime = time.gmtime(time.time() + (duration * 3600))
            leaseTo = time.strftime("%Y-%m-%d %H:%M:%S", leaseToTime)
        else: 
            leaseTo = "2030-01-01 00:00:00"
            leaseToTime = time.strptime(leaseTo, "%Y-%m-%d %H:%M:%S")
            duration = (calendar.timegm(leaseToTime) - time.time()) / 3600
        

        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        leasePolicy = machines[machine]['leasepolicy']
        if leasePolicy and duration > leasePolicy:
            raise XenRTAPIError(HTTPUnauthorized, "The policy for this machine only allows leasing for %d hours, please contact QA if you need a longer lease" % leasePolicy, canForce=False)
        
        leasedTo = machines[machine]['leaseuser']
        if leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is already leased to %s" % leasedTo, canForce=True)
        currentLeaseTime = machines[machine]['leaseto']
        if currentLeaseTime and time.gmtime(currentLeaseTime) > leaseToTime and not force:
            raise XenRTAPIError(HTTPNotAcceptable, "Machines is already leased for longer", canForce=True)

        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = %s, leasefrom = %s, comment = %s, leasereason = %s "
                    "WHERE machine = %s",
                    [leaseTo, leaseFrom, user, reason, machine])
        db.commit()
        cur.close()        

    def removeMachine(self, machine, commit=True):
        db = self.getDB()
        cur = db.cursor()
        try:
            cur.execute("DELETE FROM tblmachines WHERE machine=%s", [machine])
            cur.execute("DELETE FROM tblmachinedata WHERE machine=%s", [machine])
            if commit:
                db.commit()
        finally:
            cur.close()


class ListMachines(_MachineBase):
    PATH = "/machines"
    REQTYPE = "GET"
    SUMMARY = "Get machines matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'default': '',
          'description': 'Filter on machine status. Any of "idle", "running", "leased", "offline", "broken" - can specify multiple',
          'in': 'query',
          'items': {'enum': ['idle', 'running', 'leased', 'offline', 'broken'], 'type': 'string'},
          'name': 'status',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on site - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'site',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on pool - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'pool',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on cluster - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'cluster',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on lease user - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'user',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific machine - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'machine',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on a resource - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'resource',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on a flag - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'flag',
          'required': False,
          'type': 'array'},
         {'description': 'Limit the number of results. Defaults to unlimited',
          'in': 'query',
          'name': 'limit',
          'required': False,
          'default': 10,
          'type': 'integer'},
         {'description': 'Offset to start the results at, for paging with limit enabled.',
          'in': 'query',
          'name': 'offset',
          'required': False,
          'type': 'integer'}
          ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["machines"]
   
    def render(self):
        return self.getMachines(pools = self.getMultiParam("pool"),
                                clusters = self.getMultiParam("cluster"),
                                resources = self.getMultiParam("resource"),
                                sites = self.getMultiParam("site"),
                                status = self.getMultiParam("status"),
                                users = self.getMultiParam("user"),
                                machines = self.getMultiParam("machine"),
                                flags = self.getMultiParam("flags"),
                                pseudoHosts = self.request.params.get("pseudohosts") == "true",
                                limit=int(self.request.params.get("limit", 0)),
                                offset=int(self.request.params.get("offset", 0)))

class GetMachine(_MachineBase):
    PATH = "/machine/{name}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific machine object"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to fetch',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        machine = self.request.matchdict['name']
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        return machines[machine]

class LeaseMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "POST"
    SUMMARY = "Lease a machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to lease',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/lease" }
         }
         
        ]
    DEFINITIONS = { "lease": {
             "title": "Lease details",
             "type": "object",
             "required": ["duration", "reason"],
             "properties": {
                "duration": {
                    "type": "integer",
                    "description": "Time in hours to lease the machine. 0 means forever",
                    "default": 24},
                "reason": {
                    "type": "string",
                    "description": "Reason the machine is to be leased"},
                "force": {
                    "type": "boolean",
                    "description": "Whether to force lease if another use has the machine leased",
                    "default": False}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "lease_machine"
    PARAM_ORDER = ['name', 'duration', 'reason', 'force']

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['lease'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.lease(self.request.matchdict['name'], self.getUser(), params['duration'], params['reason'], params.get('force', False))
        return {}
        
class ReturnMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "DELETE"
    SUMMARY = "Return a leased machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to lease',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/leasereturn" }
         }
         
        ]
    DEFINITIONS = { "leasereturn": {
             "title": "Lease details",
             "type": "object",
             "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Whether to force return if another use has the machine leased",
                    "default": False}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "return_leased_machine"

    def render(self):
        try:
            if self.request.body:
                params = json.loads(self.request.body)
            else:
                params = {}
            jsonschema.validate(params, self.DEFINITIONS['leasereturn'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.return_machine(self.request.matchdict['name'], self.getUser(), params.get('force', False))
        return {}

class UpdateMachine(_MachineBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/machine/{name}"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/updatemachine" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"updatemachine": {
        "title": "Update Macine",
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": "Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)"
            },
            "status": {
                "type": "string",
                "description": "Status of the machine"
            },
            "broken": {
                "type": "object",
                "description": "Mark the machine as broken or fixed. Fields are 'broken' (boolean - whether or not the machine is broken), 'info' (string - notes about why the machine is broken), 'ticket' (string - ticket reference for this machine)",
                "properties": {
                    "broken": { "type": "boolean" },
                    "info": { "type": "string" },
                    "ticket": { "type": "string" }
                }
            },
            "addflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to add to this machine"
            },
            "delflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to remove from this machine"
            },
            "resources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            }
        }
    }}
    OPERATION_ID = "update_machine"
    PARAM_ORDER=["name", "params", "broken", "status", "resources", "addflags", "delflags"]
    SUMMARY = "Update machine details"

    def render(self):
        machine = self.request.matchdict['name']
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updatemachine'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        if j.get('params'):
            for p in j['params'].keys():
                self.updateMachineField(machine, p, j['params'][p], commit=False)
        if j.get('status'):
            self.updateMachineField(machine, "status", j['status'], allowReservedField=True, commit=False)
        if "broken" in j:

            pool = machines[machine]['pool']
            if j['broken']['broken']:
                if not pool.endswith("x"):
                    self.updateMachineField(machine, "POOL", pool + "x", commit=False)
                self.updateMachineField(machine, "BROKEN_INFO", j['broken'].get("info"), commit=False)
                self.updateMachineField(machine, "BROKEN_TICKET", j['broken'].get("ticket"), commit=False)
            else:
                if pool.endswith("x"):
                    self.updateMachineField(machine, "POOL", pool.rstrip("x"), commit=False)
                self.updateMachineField(machine, "BROKEN_INFO", None, commit=False)
                self.updateMachineField(machine, "BROKEN_TICKET", None, commit=False)
        if "addflags" in j:
            if not "PROPS" in machines[machine]['params']:
                props = []
            else:
                props = machines[machine]['params']['PROPS'].split(",")
            for f in j['addflags']:
                if not f in props:
                    props.append(f)
            self.updateMachineField(machine, "PROPS", ",".join(props), commit=False)
        if "delflags" in j:
            if "PROPS" in machines[machine]['params']:
                props = machines[machine]['params']['PROPS'].split(",")
                for f in j['delflags']:
                    if f in props:
                        props.remove(f)
                self.updateMachineField(machine, "PROPS", ",".join(props), commit=False)
        if "resources" in j:
            resources = machines[machine]['resources']

            for r in j['resources'].keys():
                if j['resources'][r] == None and r in resources:
                    del resources[r]
                elif j['resources'][r] != None:
                    resources[r] = str(j['resources'][r])

            self.updateMachineField(machine, "RESOURCES", "/".join(["%s=%s" % (x,y) for (x,y) in resources.items()]), commit=False)

        self.getDB().commit()
        return {}
    
class NewMachine(_MachineBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/machines"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the machine',
         'schema': { "$ref": "#/definitions/newmachine" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"newmachine": {
        "title": "New Macine",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the machine"
            },
            "site": {
                "type": "string",
                "description": "Site this machine belongs to"
            },
            "pool": {
                "type": "string",
                "description": "Pool this machine belongs to"
            },
            "cluster": {
                "type": "string",
                "description": "Cluster this machine belongs to"
            },
            "params": {
                "type": "object",
                "description": "Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)"
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags for this machine"
            },
            "resources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            },
            "description": {
                "type": "string",
                "description": "Description of the machine"
            }
        },
        "required": ["name", "pool", "site", "cluster"]
    }}
    OPERATION_ID = "new_machine"
    PARAM_ORDER=["name", "site", "pool", "cluster", "flags", "resources", "params"]
    SUMMARY = "Add new machine"

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newmachine'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])

        self.addMachine(j.get("name"), j.get("site"), j.get("pool"), j.get("cluster"), j.get("resources", {}), j.get("description"))

        if j.get("flags"):
            self.updateMachineField(machine, "PROPS", ",".join(j['flags']), commit=False)

        if j.get('params'):
            for p in j['params'].keys():
                self.updateMachineField(machine, p, j['params'][p], commit=False)
   
        self.getDB().commit()
        return {}

class RemoveMachine(_MachineBase):
    PATH = "/machine/{name}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes a machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to remove',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_machine"

    def render(self):
        machine = self.request.matchdict['name']
        self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        self.removeMachine(machine)
        return {}

RegisterAPI(ListMachines)
RegisterAPI(GetMachine)
RegisterAPI(LeaseMachine)
RegisterAPI(ReturnMachine)
RegisterAPI(UpdateMachine)
RegisterAPI(NewMachine)
RegisterAPI(RemoveMachine)