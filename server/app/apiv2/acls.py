from app.apiv2 import *
from pyramid.httpexceptions import *
import calendar
import app.utils
import json
import time
import jsonschema

class _AclBase(XenRTAPIv2Page):

    def getAcls(self,
                owners=[],
                ids=[],
                names=[],
                limit=None,
                offset=0,
                exceptionIfEmpty=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []

        if ids:
            conditions.append(self.generateInCondition("a.aclid", ids))
            params.extend(ids)

        if owners:
            conditions.append(self.generateInCondition("a.owner", owners))
            params.extend(owners)

        if names:
            conditions.append(self.generateInCondition("a.name", names))
            params.extend(names)

        query = "SELECT a.aclid, a.parent, a.owner, a.name FROM tblacls a"
        if conditions:
            query += " WHERE %s" % " AND ".join(conditions)

        cur.execute(query, self.expandVariables(params))

        ret = {}

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            acl = {
                "parent": rc[1],
                "owner": rc[2].strip(),
                "name": rc[3].strip()
            }

            ret[rc[0]] = acl
        if len(ret.keys()) == 0:
            if exceptionIfEmpty:
                raise XenRTAPIError(HTTPNotFound, "ACL not found")

            return ret

        for a in ret.keys():
            # Get the ACL entries
            query = "SELECT ae.prio, ae.type, ae.userid, ae.grouplimit, ae.grouppercent, ae.userlimit, ae.userpercent, ae.maxleasehours FROM tblaclentries ae WHERE ae.aclid=%s ORDER BY ae.prio"
            cur.execute(query, [a])
            entries = {}
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                entry = {
                    "type": rc[1].strip(),
                    "userid": rc[2].strip(),
                    "grouplimit": rc[3],
                    "grouppercent": rc[4],
                    "userlimit": rc[5],
                    "userpercent": rc[6],
                    "maxleasehours": rc[7]
                }
                entries[rc[0]] = entry
            ret[a]['entries'] = entries

        if limit:
            aclsToReturn = sorted(ret.keys())[offset:offset+limit]

            for a in ret.keys():
                if not a in aclsToReturn:
                    del ret[m]

        return ret

    def newAcl(self, name, parent, owner):
        db = self.getDB()
        cur = db.cursor()
        if parent:
            cur.execute("INSERT INTO tblacls (parent, owner, name) VALUES (%s, %s, %s) RETURNING aclid", [parent, owner, name])
        else:
            cur.execute("INSERT INTO tblacls (owner, name) VALUES (%s, %s) RETURNING aclid", [owner, name])
        rc = cur.fetchone()
        aclid = rc[0]
        db.commit()
        return self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True)

    def updateAcl(self, aclid, name, parent):
        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblacls SET name=%s, parent=%s WHERE aclid=%s", [name, parent, aclid])
        db.commit()
        return self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True)

    def removeAcl(self, aclid):
        # Check the ACL isn't in use anywhere
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM tblmachines WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        count = rc[0]
        if count > 0:
            raise XenRTAPIError(HTTPPreconditionFailed, "ACL in use by %d machines" % count)
        cur.execute("DELETE FROM tblacls WHERE aclid=%s", [aclid])
        db.commit()

    def checkAcl(self, aclid, user):
        """Check the ACL exists and is accessible by the given user"""

        # TODO: Allow XenRT admins to perform operations here
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT owner FROM tblacls WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        if not rc:
            raise XenRTAPIError(HTTPNotFound, "ACL not found")
        owner = rc[0].strip()
        if owner != user:
            raise XenRTAPIError(HTTPForbidden, "You are not the owner of this ACL")

class ListAcls(_AclBase):
    PATH = "/acls"
    REQTYPE = "GET"
    SUMMARY = "Get ACLs matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'description': 'Filter on ACL owner - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'owner',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific ACL - can specify multiple',
          'in': 'query',
          'items': {'type': 'integer'},
          'name': 'id',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific ACL - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'name',
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
          'type': 'integer'},
          ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["acls"]
   
    def render(self):
        return self.getAcls(owners = self.getMultiParam("owner"),
                            ids = self.getMultiParam("ids"),
                            names = self.getMultiParam("name"),
                            limit=int(self.request.params.get("limit", 0)),
                            offset=int(self.request.params.get("offset", 0)))

class GetAcl(_AclBase):
    PATH = "/acl/{id}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL id to fetch',
         'type': 'integer'}]
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"}}

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        acls = self.getAcls(limit=1, ids=[aclid], exceptionIfEmpty=True)
        return acls[aclid]

class NewAcl(_AclBase):
    WRITE = True
    PATH = "/acls"
    REQTYPE = "POST"
    SUMMARY = "Submits a new ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the ACL required',
         'schema': { "$ref": "#/definitions/newacl" }
        }
    ]
    DEFINITIONS = {"newacl": {
        "title": "New ACL",
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for new ACL"
            },
            "parent": {
                "type": "integer",
                "description": "ID of any parent ACL"
            }
        }
    }}
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "new_acl"
    PARAM_ORDER=["name", "parent"]

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newacl'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        return self.newAcl(name=j.get("name"),
                           parent=j.get("parent"),
                           owner=self.getUser())

class UpdateAcl(_AclBase):
    WRITE = True
    PATH = "/acl/{id}"
    REQTYPE = "POST"
    SUMMARY = "Update ACL details"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL ID to update',
         'type': 'integer'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/updateacl" }
        }
    ]
    DEFINITIONS = {"updateacl": {
        "title": "Update ACL",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of ACL"
            },
            "parent": {
                "type": "integer",
                "description": "ID of any parent ACL"
            }
        }
    }}
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"},
                  "403": {"description": "No permission to update the specified ACL"}}
    OPERATION_ID = "update_acl"
    PARAM_ORDER=["name", "parent"]

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        self.checkAcl(aclid, self.getUser())
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updateacl'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        return self.updateAcl(aclid, name=j.get("name"), parent=j.get("parent"))

class RemoveAcl(_AclBase):
    WRITE = True
    PATH = "/acl/{id}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes an ACL"
    TAGS = ["acls"]
    PARAMS = [
        {'name': 'id',
         'in': 'path',
         'required': True,
         'description': 'ACL ID to remove',
         'type': 'integer'}
    ]
    RESPONSES = { "200": {"description": "Successful response"},
                  "404": {"description": "ACL not found"},
                  "412": {"description": "ACL in use by one or more machines"},
                  "403": {"description": "No permission to remove the specified ACL"}}
    OPERATION_ID = "remove_acl"

    def render(self):
        aclid = self.getIntFromMatchdict("id")
        self.checkAcl(aclid, self.getUser())
        self.removeAcl(aclid)
        return {}

RegisterAPI(ListAcls)
RegisterAPI(GetAcl)
RegisterAPI(NewAcl)
RegisterAPI(UpdateAcl)
RegisterAPI(RemoveAcl)
