##NOTE THAT THIS TOOL RUNS FROM THE COMMAND LINE BUT NOT FROM ARCGIS!
##  This is weird. And I'm not sure what the problem is. (RH)
"""
script to ease construction of CSDGM2-style metadata for an NCGMP09-style geodatabase.

To use,
    Run ValidateDatabase to make sure that the database is complete and there are
       no missing DMU, Glossary, or DataSources entries
    In ArcCatalog, go to Customize>Options>Metadata and set Metadata Style to
       "FGDC CSDGM Metadata".  OK and exit. 
    In ArcCatalog, use the ArcGIS metadata editor to complete the record for the
       GeologicMap feature dataset. Save. NOTE THAT whatever errors or you create
       in this master metadata record will be faithfully propagated to metadata
       records for all parts of the geodatabase!
    Run script NCGMP09v11_MetadataCSDGM2_Arc10.1.py. This script will:
       Export the GeologicMap metadata record in CSDGM2 format
       Polish this metadata slightly for use as a master record
       For the geodatabase as a whole and for each entity (table, feature dataset,
        feature class) in the geodatabase:
           Copies the master record.
           Adds supplemental information (ArcGIS reports this in Resouce:Details)
              about the the NCGMP09 standard and continents of the geodatabase. 
           Adds a description of the entity taken from the NCGMP09 documentation.
           Adds entity-attribute information taken from the NCGMP09 documentation
              and the DMU, Glossary, and DataSources tables of the geodatabase.
           Writes this XML to a file in the directory that contains the geodatabase.
           Imports this XML into the geodatabase as metadata for the appropriate entity.
    Look at file <geodatabasename>-metadataLog.txt to see what parts of which metadata
      records need to be completed by hand. This will occur wherever you extend the
      database schema beyond the schema outlined in the NCGMP09 documentation.
      (IF YOU EXPECT TO MAKE METADATA FOR MANY GEODATABASES THAT HAVE THE SAME EXTENSIONS,
      modify NCGMP09v11_Definition.py to include description of your extensions.)
    Inspect metadata records in ArcCatalog (the Description tab) to see that they are
      complete.
    Open saved XML files in browser to see that they are appropriate. Scan for duplicate
      entries. 

You want ISO metadata? Change your Metadata Style and fix records using the
ArcCatalog metadata editor. Export as ISO of your flavor, insofar as ArcCatalog allows.
Let us know how this works.

Usage: prompt>ncgmp09v1.1_MetadataCSDGM2_Arc10.1.py <geodatabase>

Ralph Haugerud and Evan Thoms, US Geological Survey
rhaugerud@usgs.gov, ethoms@usgs.gov    
"""

import arcpy, sys, os.path, copy
from NCGMP09v11_Definition import enumeratedValueDomainFieldList, rangeDomainDict, unrepresentableDomainDict, attribDict, entityDict
from xml.dom.minidom import *

versionString = 'NCGMP09v1.1_MetadataCSDGM2_Arc10.1.py, version of 5 February 2013'
translator = arcpy.GetInstallInfo("desktop")["InstallDir"]+'Metadata/Translator/ARCGIS2FGDC.xml'

debug = False

ncgmp = 'NCGMP09 v1.1'
ncgmpFullRef = '"NCGMP09--draft standard format for digital publication of geologic maps, version 1.1", available at http://ngmdb.usgs.gov/Info/standards/NCGMP09/'

gdbDesc0a = """ is a composite geodataset that conforms to
"""+ncgmpFullRef+'. '
gdbDesc0b = """ is part of a composite geodataset that conforms to
"""+ncgmpFullRef+'. '

gdbDesc2 = """
Metadata records associated with each of these elements contain more detailed descriptions 
of their purposes, constituent entities, and attributes. Non-spatial tables DataSources, 
DescriptionOfMapUnits, and Glossary store metadata. All spatial features and some non-spatial 
features have related entries in table DataSources. Table DescriptionOfMapUnits defines and 
describes geologic map units that are delimited in feature class MapUnitPolys. Most technical 
terms used as feature attributes (including all TYPE terms and all CONFIDENCE terms) are 
defined in table Glossary. Most features have explicit internal feature-level metadata, including 
LocationConfidenceMeters, one or more Source attributes, and--as appropriate--ExistenceConfidence, 
IdentityConfidence, and OrientationConfidenceDegrees. Two shapefile versions of the dataset are 
also available. The COMPLETE shapefile version consists of shapefiles, DBF files, and delimited 
text files and retains all information in the native geodatabase, but has limited usability. The 
SIMPLE shapefile version consists only of shapefiles and is easily used, but lacks some 
information present in the native geodatabase. 
"""

def addMsgAndPrint(msg, severity=0): 
    try: 
      for string in msg.split('\n'): 
        # Add appropriate geoprocessing message 
        if severity == 0: 
            arcpy.AddMessage(string) 
        elif severity == 1: 
            arcpy.AddWarning(string) 
        elif severity == 2: 
            arcpy.AddError(string) 
    except: 
        pass

def __appendOrReplace(rootNode,newNode,nodeTag):
    if len(rootNode.getElementsByTagName(nodeTag)) == 0:
        rootNode.appendChild(newNode)
    else:
        rootNode.replaceChild(newNode,rootNode.getElementsByTagName(nodeTag)[0])

def __fieldNameList(fc):
    #Returns a list of field names from Field.name in arcpy.ListFields
    fldList = arcpy.ListFields(fc)
    nameList = []
    for fld in fldList:
        if not fld.name in ('OBJECTID', 'SHAPE','Shape', 'Shape_Length', 'Shape_Area'):
            nameList.append(fld.name)    
    return nameList

def __findInlineRef(sourceID):
    # finds the Inline reference for each DataSource_ID
    query = '"DataSources_ID" = \'' + sourceID + '\''
    rows = arcpy.SearchCursor(dataSources, query)
    row = rows.next()
    if not row is None:
        #return row.Inline
        return row.Source
    else:
        return ""

def __newElement(dom,tag,text):
    nd = dom.createElement(tag)
    ndText = dom.createTextNode(text)
    nd.appendChild(ndText)
    return nd

def __updateAttrDef(fld,dom):
    ##element tag names are
    ## attr             = Attribute
    ## attrlabl         = Attribute_Label
    ## attrdef          = Attribute_Definition
    ## attrdefs         = Attribute_Definition_Source
    labelNodes = dom.getElementsByTagName('attrlabl')
    for attrlabl in labelNodes:
        if attrlabl.firstChild.data == fld:
            attr = attrlabl.parentNode       
            if fld.find('_ID') > -1:
                # substitute generic _ID field for specific
                attrdefText = attribDict['_ID']
            else:
                attrdefText = attribDict[fld]
            attrdef = __newElement(dom,'attrdef',attrdefText)
            __appendOrReplace(attr,attrdef,'attrdef')
            attrdefs = __newElement(dom,'attrdefs',ncgmp)
            __appendOrReplace(attr,attrdefs,'attrdefs')
    return dom

def __updateEdom(fld, defs, dom):
    ##element tag names are
    ## attr             = Attribute
    ## attrdomv         = Attribute_Domain_Values
    ## edom             = Enumerated_Domain
    ## edomv            = Enumerated_Domain_Value
    ## edomd            = Enumerated_Domain_Definition
    ## edomvds          = Enumerated_Domain_Value_Definition_Source
    labelNodes = dom.getElementsByTagName('attrlabl')
    for attrlabl in labelNodes:
        if attrlabl.firstChild.data == fld:
            attr = attrlabl.parentNode
            attrdomv = dom.createElement('attrdomv')
            for k in defs.iteritems():
                edom = dom.createElement('edom')
                edomv = __newElement(dom,'edomv',k[0])
                edomvd = __newElement(dom,'edomvd',k[1][0])
                edom.appendChild(edomv)
                edom.appendChild(edomvd)
                if len(k[1][1]) > 0:
                    edomvds = __newElement(dom,'edomvds',k[1][1])
                    edom.appendChild(edomvds)                                
                attrdomv.appendChild(edom)
            __appendOrReplace(attr,attrdomv,'attrdomv')
    return dom

def __updateEntityAttributes(fc, fldList, dom, logFile):
    """For each attribute (field) in fldList,
        adds attribute definition and definition source,
        classifies as range domain, unrepresentable-value domain or enumerated-value domain, and 
            for range domains, adds rangemin, rangemax, and units;
            for unrepresentable value domains, adds unrepresentable value statement; 
            for enumerated value domains:
            1) Finds all controlled-vocabulary fields in the table sent to it
            2) Builds a set of unique terms in each field, ie, the domain
            3) Matches each domain value to an entry in the glossary
            4) Builds a dictionary of term:(definition, source) items
            5) Takes the dictionary items and put them into the metadata
              document as Attribute_Domain_Values
        Field MapUnit in table DescriptionOfMapUnits is treated as a special case.
        """
    cantfindTerm = []
    cantfindValue = []
    for fld in fldList:      
        addMsgAndPrint( '      Field: '+ fld)
        # if is _ID field or if field definition is available, update definition
        if fld.find('_ID') > -1 or attribDict.has_key(fld):
            dom = __updateAttrDef(fld,dom)
        else:
            cantfindTerm.append(fld)
        #if this is an _ID field
        if fld.find('_ID') > -1:
            dom = __updateUdom(fld,dom,unrepresentableDomainDict['_ID'])
        #if this is another unrepresentable-domain field
        if unrepresentableDomainDict.has_key(fld):
            dom = __updateUdom(fld,dom,unrepresentableDomainDict[fld])
        #if this is a defined range-domain field
        elif rangeDomainDict.has_key(fld):
            dom = __updateRdom(fld,dom)
        #if this is MapUnit in DMU
        elif fld == 'MapUnit' and fc == 'DescriptionOfMapUnits':
            dom = __updateUdom(fld,dom,unrepresentableDomainDict['default'])
        #if this is a defined Enumerated Value Domain field
        elif fld in enumeratedValueDomainFieldList:
            valList = []
            #create a search cursor on the field
            rows = arcpy.SearchCursor(fc,'','', fld)
            row = rows.next()           
            #collect all values/terms in that field
            while row:
                if not row.getValue(fld) is None:
                    valList.append(row.getValue(fld))
                row = rows.next()            
            #uniquify the list by converting it to a set object
            valList = set(valList)
            #create an empty dictionary object to hold the matches between the unique terms
            #and their definitions (grabbed from the glossary)
            defs = {}
            #for each unique term, try to create a search cursor of just one record where the term
            #matchs a Term field value from the glossary
            if fld == 'MapUnit' and fc <> 'DescriptionOfMapUnits':
                for t in valList:
                    query = '"MapUnit" = \'' + t + '\''
                    rows = arcpy.SearchCursor(DMU, query)
                    row = rows.next()
                    #if the searchcursor contains a row
                    if row:
                        #create an entry in the dictionary of term:[definition, source] key:value pairs
                        #this is how we will enumerate through the enumerated_domain section
                        defs[t] = []
                        defs[t].append(row.FullName.encode('utf_8'))
                        defs[t].append('this report, table DescriptionOfMapUnits')
                    else:
                        if not t in ('',' '): cantfindValue.append([fld,t])
            elif fld.find('SourceID') > -1:  # is a source field
                for t in valList:
                    query = '"DataSources_ID" = \'' + t + '\''
                    rows = arcpy.SearchCursor(dataSources, query)
                    row = rows.next()
                    #if the searchcursor contains a row
                    if row:
                        #create an entry in the dictionary of term:[definition, source] key:value pairs
                        #this is how we will enumerate through the enumerated_domain section
                        defs[t] = []
                        defs[t].append(row.Source.encode('utf_8'))
                        defs[t].append('this report, table DataSources')
                    else:
                        cantfindValue.append([fld,t])
            else:
                for t in valList:
                    query = '"Term" = \'' + t + '\''
                    rows = arcpy.SearchCursor(gloss, query)
                    row = rows.next()
                    #if the searchcursor contains a row
                    if row:
                        #create an entry in the dictionary of term:[definition, source] key:value pairs
                        #this is how we will enumerate through the enumerated_domain section
                        defs[t] = []
                        defs[t].append(row.Definition.encode('utf_8'))
                        defs[t].append(__findInlineRef(row.DefinitionSourceID).encode('utf_8'))
                    else:
                        cantfindValue.append([fld,t])
            dom = __updateEdom(fld, defs, dom)
        else:  #presumed to be an unrepresentable domain
            dom = __updateUdom(fld,dom,unrepresentableDomainDict['default'])
    if len(cantfindValue) > 0:
        logFile.write('Missing enumerated-domain values\n')
        logFile.write('  ENTITY     TERM     VALUE\n')
        for term in cantfindValue:
            logFile.write('  '+fc+'  '+term[0]+' **'+term[1]+'**\n')
    if len(cantfindTerm) > 0:
        logFile.write('Missing terms\n')
        logFile.write('  ENTITY     TERM\n')
        for term in cantfindTerm:
            logFile.write('  '+fc + '  '+term+'\n')
    return dom

def __updateRdom(fld,dom):
    labelNodes = dom.getElementsByTagName('attrlabl')
    for attrlabl in labelNodes:
        if attrlabl.firstChild.data == fld:
            attr = attrlabl.parentNode
            attrdomv = dom.createElement('attrdomv')
            rdom = dom.createElement('rdom')
            rdommin = __newElement(dom,'rdommin',rangeDomainDict[fld][0])
            rdom.appendChild(rdommin)
            rdommax = __newElement(dom,'rdommax',rangeDomainDict[fld][1])
            rdom.appendChild(rdommax)
            attrunit = __newElement(dom,'attrunit',rangeDomainDict[fld][2])
            rdom.appendChild(attrunit)
            attrdomv.appendChild(rdom)
            __appendOrReplace(attr,attrdomv,'attrdomv')
            return dom

def __updateUdom(fld,dom,udomTextString):
    labelNodes = dom.getElementsByTagName('attrlabl')
    for attrlabl in labelNodes:
        if attrlabl.firstChild.data == fld:
            attr = attrlabl.parentNode
            attrdomv = dom.createElement('attrdomv')
            udom = __newElement(dom,'udom',udomTextString)
            attrdomv.appendChild(udom)
            __appendOrReplace(attr,attrdomv,'attrdomv')
    return dom

def addSupplinf(dom,supplementaryInfo):
    rtNode = dom.getElementsByTagName('descript')[0]
    siNode = __newElement(dom,'supplinf',supplementaryInfo)
    __appendOrReplace(rtNode,siNode,'supplinf')
    return dom

def cleanTitle(dom):
    # trims all ": table...", ":  feature..." from title
    title = dom.getElementsByTagName('title')[0]
    titleText = title.firstChild.data
    #if debug: addMsgAndPrint(titleText)
    for txt in (': feature',': table'):
        cn = titleText.find(txt)
        if cn > 0:
            titleText = titleText[0:cn]
    title.firstChild.data = titleText
    return dom

def eaoverviewDom(dom,eainfo,eaoverText,edcTxt):
    overview = dom.createElement('overview')
    eaover = __newElement(dom,'eaover',eaoverText)
    overview.appendChild(eaover)
    eadetcit = __newElement(dom,'eadetcit',edcTxt)
    overview.appendChild(eadetcit)
    eainfo.appendChild(overview)
    return dom

def purgeChildren(dom,nodeTag):
    nodes = dom.getElementsByTagName(nodeTag)
    for aNode in nodes:
        while len(aNode.childNodes) > 0:
            aNode.removeChild(aNode.lastChild)
    return dom

def purgeIdenticalSiblings(dom,ndTag,ndTxt):
    nodes = dom.getElementsByTagName(ndTag)
    parentNodes = []
    n = 0
    for nd in nodes:
        if nd.firstChild.data == ndTxt:
            parentNodes.append(nd.parentNode)
            n = n+1
    for i in range(1,n):
        grandparent = parentNodes[i].parentNode
        grandparent.removeChild(parentNodes[i])
    return dom

def titleSuffix(dom,suffix):
    # adds suffix to title text
    title = dom.getElementsByTagName('title')[0]
    titleText = title.firstChild.data
    if titleText.find(suffix) == -1:  # titleSuffix isn't already present
        title.firstChild.data = titleText+suffix
    return dom

def updateTableDom(dom,fc,logFile):
    #def __updateTable(domMR,fc,gdbFolder,titleSuffix,logFile,isAnno):
    #try to export metadata from fc
    desc = arcpy.Describe(fc)
    if desc.datasetType == 'FeatureClass' and desc.FeatureType == 'Annotation':
        isAnno = True
    else: isAnno = False 
    if entityDict.has_key(fc):
        hasDesc = True
        descText = entityDict[fc]
        descSourceText = ncgmp
    else:
        hasDesc = False
        if not isAnno:
            descText = '**Need Description of '+fc+'**'
            descSourceText = '**Need Description Source**'
            logFile.write('No description for entity '+fc+'\n')
            logFile.write('No description source for entity '+fc+'\n')

    eainfo = dom.getElementsByTagName('eainfo')[0]
    # DELETE EXISTING CHILD NODES
    while len(eainfo.childNodes) > 0:
        eainfo.removeChild(eainfo.lastChild)
    if isAnno:
        if hasDesc: eaoverText = descText
        else: eaoverText = 'annotation feature class'
        if hasDesc: edcTxt = descSourceText
        else: edcTxt = 'See ESRI documentation for structure of annotation feature classes.'
        # add overview to dom
        dom = eaoverviewDom(dom,eainfo,eaoverText,edcTxt)
        
        #overview = dom.createElement('overview')
        #eaover = __newElement(dom,'eaover',eaoverText)
        #overview.appendChild(eaover)
        #eadetcit = __newElement(dom,'eadetcit',edcTxt)
        #overview.appendChild(eadetcit)
        #eainfo.appendChild(overview)
    else:  # is table or non-Anno feature class
        # check for e-a detailed node, add if necessary
        if len(eainfo.getElementsByTagName('detailed')) == 0:
            #add detailed/enttyp/enttypl nodes
            detailed = dom.createElement('detailed')
            enttyp = dom.createElement('enttyp')
            enttypl = __newElement(dom,'enttypl',fc)
            enttypd = __newElement(dom,'enttypd',descText)
            enttypds = __newElement(dom,'enttypds',descSourceText)
            for nd in enttypl,enttypd,enttypds:
                enttyp.appendChild(nd)
            detailed.appendChild(enttyp)
            eainfo.appendChild(detailed)
            
        ##check that each field has a corresponding attr node
        #get a list of the field names in the fc
        fldNameList = __fieldNameList(fc)    
        #get list of attributes in this metadata record
        #  we assume there eainfoNode has only one 'detailed' child
        attrlablNodes = eainfo.getElementsByTagName('attrlabl')
        attribs = []
        detailed = dom.getElementsByTagName('detailed')[0]
        for nd in attrlablNodes:
            attribs.append(nd.firstChild.data)
        for fieldName in fldNameList:
            if not fieldName in attribs:
                attr = dom.createElement('attr')
                attrlabl = __newElement(dom,'attrlabl',fieldName)
                attr.appendChild(attrlabl)
                detailed.appendChild(attr)                
        #update the entity description and entity description source
        if entityDict.has_key(fc) or ( fc[0:2] == 'CS' and entityDict.has_key(fc[2:]) ):
            enttypl = dom.getElementsByTagName('enttypl')
            if len(enttypl) > 0:
                enttyp = enttypl[0].parentNode
                # entity description node
                if fc[0:2] == 'CS':
                    descriptionText = entityDict[fc[2:]]
                else:
                    descriptionText = entityDict[fc]
                newEnttypd = __newElement(dom,'enttypd',descriptionText)
                __appendOrReplace(enttyp,newEnttypd,'enttypd')
                # entity description source node
                newEnttypds = __newElement(dom,'enttypds',ncgmp)
                __appendOrReplace(enttyp,newEnttypds,'enttypds')                           
        #update attribute descriptions and value domains
        dom = __updateEntityAttributes(fc, fldNameList, dom, logFile)
    return dom

def writeDomToFile(dom,fileName):
    outf = open(fileName,'w')
    dom.writexml(outf)
    outf.close()

def writeGdbDesc1(gdb):
    desc = 'The geodatabase contains the following elements: '
    arcpy.env.workspace = gdb
    for aTable in arcpy.ListTables():
        desc = desc+'non-spatial table '+ aTable+'; '
    for anFds in arcpy.ListDatasets():
        desc = desc + 'feature dataset '+anFds+' which contains '
        fcs = arcpy.ListFeatureClasses('','All',anFds)
        if len(fcs) == 1:
            desc = desc + 'feature class '+fcs[0]+'; '
        else:
            for n in range(0,len(fcs)-2):
                desc = desc+'feature class '+fcs[n]+', '
            desc = desc+'and feature class '+fcs[len(fcs)-1]+'; '
    desc = desc[:-2]+'. '
    return desc

    
##############################################################################
inGdb = sys.argv[1]

inGdb = os.path.abspath(inGdb)
workDir = os.path.dirname(inGdb)
gdb = os.path.basename(inGdb)

gloss = os.path.join(inGdb, 'Glossary')
dataSources = os.path.join(inGdb, 'DataSources')
DMU = os.path.join(inGdb, 'DescriptionOfMapUnits')
logFileName = inGdb+'-metadataLog.txt'
xmlFileMR = gdb+'-MR.xml'
xmlFileGdb = gdb+'.xml'

# export master record
fXML = workDir+'/'+gdb+ '.xml'
addMsgAndPrint('fXML = '+fXML)
if os.path.exists(fXML):
    os.remove(fXML)
gdbObj = inGdb+'/GeologicMap'
arcpy.ExportMetadata_conversion(gdbObj,translator,fXML)

addMsgAndPrint('  Metadata for GeologicMap exported to file ')
addMsgAndPrint('    '+fXML)

# parse xml to DOM
try:
    domMR = xml.dom.minidom.parse(fXML)
    addMsgAndPrint('  Master record parsed successfully')
    # should then delete xml file
    if not debug: os.remove(fXML)
except:
    addMsgAndPrint(arcpy.GetMessages())
    addMsgAndPrint('Failed to parse '+fXML)
    raise arcpy.ExecuteError
    sys.exit()

# clean up master record
## purge of eainfo and spdoinfo
addMsgAndPrint( 'A')
for nodeTag in ('eainfo','spdoinfo'):
    domMR = purgeChildren(domMR,nodeTag)
## get rid of extra <themekt>ISO 19115 Topic Categories entries
#domMR = purgeIdenticalSiblings(domMR,'themekt','ISO 19115 Topic Categories')
## fix title
domMR = cleanTitle(domMR)
##  ensure that there is an eainfo node
try:
    eanode = domMR.getElementsByTagName('eainfo')[0]
except:
    rtNode = domMR.getElementsByTagName('metadata')[0]
    eanode = domMR.createElement('eainfo')
    rtNode.appendChild(eanode)

gdbDesc1 = writeGdbDesc1(gdb)
writeDomToFile(domMR,xmlFileMR)
addMsgAndPrint('  Running mp on master metadata record '+xmlFileMR+':')
if os.path.exists(logFileName):
    os.remove(logFileName)
arcpy.USGSMPTranslator_conversion(xmlFileMR,'#','#','#',logFileName)
for aline in open(logFileName,'r').readlines():
    addMsgAndPrint(aline[:-1])
addMsgAndPrint(' ')


logFile = open(logFileName,'a')

# import to geodatabase as whole
arcpy.env.workspace = workDir
supplementaryInfo = gdb+gdbDesc0a+gdbDesc1+gdbDesc2
dom = addSupplinf(domMR,supplementaryInfo)    
addMsgAndPrint('  Importing XML to metadata for GDB as a whole')
writeDomToFile(dom,xmlFileGdb)
arcpy.ImportMetadata_conversion(xmlFileGdb,'FROM_FGDC',inGdb,'ENABLED')

# import to tables
arcpy.env.workspace = inGdb
tables = arcpy.ListTables()
for aTable in tables:
    revisedMetadata = gdb+'-'+aTable+'.xml'
    addMsgAndPrint('  Creating XML for '+aTable)
    dom = xml.dom.minidom.parse(xmlFileMR)
    dom = titleSuffix(dom,': table '+aTable)
    supplementaryInfo = 'Table '+aTable+gdbDesc0b+gdbDesc1+gdbDesc2
    dom = addSupplinf(dom,supplementaryInfo)    
    dom = updateTableDom(dom,aTable,logFile)    
    addMsgAndPrint('  Importing XML to metadata for table '+aTable)
    writeDomToFile(dom,revisedMetadata)
    arcpy.ImportMetadata_conversion(revisedMetadata,'FROM_FGDC',inGdb+'/'+aTable,'ENABLED')

# import to feature datasets and constituent feature classes
arcpy.env.workspace = inGdb
fds = arcpy.ListDatasets('','Feature')
for anFds in fds:
    revisedMetadata = gdb+'-'+anFds+'.xml'
    addMsgAndPrint('  Creating XML for '+anFds)
    dom = xml.dom.minidom.parse(xmlFileMR)
    dom = titleSuffix(dom,': feature dataset '+anFds)
    supplementaryInfo = 'Feature dataset '+anFds+gdbDesc0b+gdbDesc1+gdbDesc2
    dom = addSupplinf(dom,supplementaryInfo)
    if entityDict.has_key(anFds):
        overText = entityDict[anFds]
        overSrc = ncgmp
    elif anFds.find('CrossSection') == 0:
        overText = entityDict['CrossSection']
        overSrc = ncgmp
    else:
        overText = '**Need Description of '+anFds+'**'
        overSrc = '**Need Description Source**'
        logFile.write('No description for entity '+anFds+'\n')
        logFile.write('No description source for entity '+anFds+'\n')
    eainfo = dom.getElementsByTagName('eainfo')[0]
    dom = eaoverviewDom(dom,eainfo,overText,overSrc)
    addMsgAndPrint('  Importing XML to metadata for '+anFds)
    writeDomToFile(dom,revisedMetadata)
    arcpy.ImportMetadata_conversion(revisedMetadata,'FROM_FGDC',inGdb+'/'+anFds,'ENABLED')   
    fcs = arcpy.ListFeatureClasses('','All',anFds)
    del dom
    for anFc in fcs:
        revisedMetadata = gdb+'-'+anFc+'.xml'
        addMsgAndPrint('    Creating XML for '+anFc)
        dom = xml.dom.minidom.parse(xmlFileMR)
        supplementaryInfo = 'Feature class '+anFc+gdbDesc0b+gdbDesc1+gdbDesc2
        dom = addSupplinf(dom,supplementaryInfo)
        dom = updateTableDom(dom,anFc,logFile)
        addMsgAndPrint('    Importing XML to metadata for '+anFc)
        writeDomToFile(dom,revisedMetadata)
        arcpy.ImportMetadata_conversion(revisedMetadata,'FROM_FGDC',inGdb+'/'+anFds+'/'+anFc,'ENABLED')
        del dom

addMsgAndPrint('\nBe sure to check file '+os.path.basename(logFileName)+' !')
logFile.close()


