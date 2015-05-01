import urllib, urllib2, json, math, re
from datetime import datetime, timedelta
import xenrt
from xenrt.lazylog import step, comment, log, warning

class LabCostPerTechArea():

    def __init__(self, suiteId, arglist):
        self.suiteId = suiteId
        self.nbrOfSuiteRunsToCheck = 5

    def generate(self):

        # TODO check if we have JSON already created for suite, if exists and not outdated(not older than 30 days), skip generation and use it.
        ####
    
        step("Get latest suite run history")
        u = urllib.urlopen("%s/suitehistoryjson/%s" % (xenrt.TEC().lookup("TESTRUN_URL"), self.suiteId))
        suiteRunData = json.loads(u.read().strip())
        suiteRunIds = [int(srid) for srid in suiteRunData.keys()]
        suiteRunIds.sort(reverse=True)

        step("Get testcase and sequence details from suite")
        xenrt.TEC().config.setVariable("JIRA_TICKET_TAG", "Test")
        suite = xenrt.suite.Suite(self.suiteId)
        suiteData = {seq.seq: {"testcases":[tc.split("_")[0] if re.match("^TC-\d+$", tc.split("_")[0]) else None for tc in seq.listTCsInSequence(quiet=True)]} for seq in suite.sequences}

        step("Get job details")
        for srid in suiteRunIds[:min(self.nbrOfSuiteRunsToCheck,len(suiteRunIds))]:
            log("Fetching job details from suite run %d" %srid)
            jobData= xenrt.APIFactory().get_jobs(status="done", suiterun=srid, params=True, limit=len(suiteData))
            for job in jobData:
                try:
                    seq = jobData[job]['params']['DEPS']
                    startTime = datetime.strptime(jobData[job]['params']['STARTED'][:-4],"%a %b %d %H:%M:%S %Y")
                    finishTime = datetime.strptime(jobData[job]['params']['FINISHED'][:-4],"%a %b %d %H:%M:%S %Y")
                    executionTime = finishTime-startTime
                    nbrOfMachines = int(jobData[job]['params']['MACHINES_REQUIRED'])
                    if seq in suiteData:
                        if not "jobCount" in suiteData[seq]:
                            suiteData[seq]["runtime"]= executionTime * nbrOfMachines
                            suiteData[seq]["jobCount"]= 1
                        else:
                            suiteData[seq]["runtime"]= ( executionTime * nbrOfMachines + suiteData[seq]["runtime"]*suiteData[seq]["jobCount"] ) / (suiteData[seq]["jobCount"]+1)
                            suiteData[seq]["jobCount"] += 1
                except Exception,e: 
                    log("WARNING: Job %s has exception: %s" % (job, e))

        step("Processing Data: seq as primary key -> testcase as primary id")
        tcData={}
        TimeMissingTAInfo = timedelta(0, 0, 0)
        tcMissingHistory = []
        for seq in suiteData:
            tcCountInSeq = len(suiteData[seq]['testcases'])
            if not "runtime" in suiteData[seq]:
                tcMissingHistory.extend(suiteData[seq]['testcases'])
            elif not tcCountInSeq:
                TimeMissingTAInfo += suiteData[seq]['runtime']
            else:
                for tc in suiteData[seq]['testcases']:
                    if tc in tcData and 'runtime' in tcData[tc]:
                        #possibly testcase has multiple runs, then we add time
                        tcData[tc]['runtime'] += suiteData[seq]['runtime']/tcCountInSeq
                    elif tc:
                        tcData.update( {tc:{ 'runtime':( suiteData[seq]['runtime']/tcCountInSeq) }})

        step("Fetching TechArea for each TA from Jira.")
        j = xenrt.jiralink.getJiraLink()
        count=0
        tcIds = tcData.keys()
        totalCount = len(tcIds)
        maxCountAllowed = 25
        while count <= totalCount:
            log("\tfetching part %d/%d"% (math.ceil(count/maxCountAllowed+1), math.ceil(totalCount/maxCountAllowed+1)))
            tcIdsSub= tcIds[count:min(count+maxCountAllowed, totalCount)]
            count +=maxCountAllowed
            query='Key in (%s)' % ",".join(tcIdsSub)
            result = j.jira.search_issues(query, maxResults=maxCountAllowed)
            [tcData[issue.key].update({'techarea':([comp.name for comp in issue.fields.components][0])}) if issue.fields.components else None for issue in result]

        step("Processing Data. testcase as primary key -> techArea as primary key")
        techAreaData = {'Unknown' : TimeMissingTAInfo.total_seconds()}
        for tc in tcData:
            if not 'techarea' in tcData[tc]:
                techAreaData['Unknown'] += tcData[tc]['runtime'].total_seconds()
            elif not tcData[tc]['techarea'] in techAreaData:
                techAreaData[tcData[tc]['techarea']]= tcData[tc]['runtime'].total_seconds()
            else:
                techAreaData[tcData[tc]['techarea']] += tcData[tc]['runtime'].total_seconds()

        return (techAreaData, tcMissingHistory)

def generateLabCostPerTechArea(suiteId):
    cls = LabCostPerTechArea(suiteId)
    data, tcMissingData = cls.generate()

    # TODO : save data as JSON to a file, to be used by a website.
    
    log("Lab cost per TA for suite %s : %s" % (suiteId, data))
    warning("Testcases not having run history: %s" % (tcMissingData))
