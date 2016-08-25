import csv
import sys
import getopt

import atexit

from pyVim import connect
from pyVmomi import vim
from pyVmomi import vmodl

import logging


#######################################################
#                    LOGGER                           #
logger = logging.getLogger('getVmMetaData')
logger.setLevel(logging.INFO)

# create file handler which logs even debug messages
fh = logging.FileHandler('debug.log')
fh.setLevel(logging.DEBUG)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
formatter = logging.Formatter('%(asctime)s - %(message)s')
ch.setFormatter(formatter)

# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)
#
#######################################################





CSV_FIELDS = ['uuid', 'name', 'nic', 'user', 'enterprise', 'domainType', 'domain', 'zone', 'network', 'networktype', 'ip', 'vport', 'policy-group', 'redirection-target']
vm_properties = ["name", "config.uuid", "config.extraConfig"]


import config as config


def getNuageMetaData(extraConfig):
    vmMetadata = []
    if extraConfig is None or len(extraConfig)<=0:
        return []

    rawMetaDatas=[]
    for option in extraConfig:
        if 'nuage' in option.key.lower():
            rawMetaDatas.append( (option.key, option.value) )

    enterprise=''
    user = ''
    nicKeys = {}
    if rawMetaDatas and len(rawMetaDatas)>0:
        #Get each nicX config
        for (key, value) in rawMetaDatas:
            if 'enterprise' in key:
                enterprise = value
            elif 'user' in key:
                user = value
            elif '.nic' in key:
                split_key = key.split('.')
                if split_key and len(split_key)>=3:
                    nicId = split_key[1]
                    nicParam = split_key[2]

                    if nicId not in nicKeys.keys():
                        nicKeys[nicId] = {}
                        nicKeys[nicId]['nic'] = nicId
                        nicKeys[nicId]['enterprise'] = enterprise
                        nicKeys[nicId]['user'] = user

                    if nicId in nicKeys.keys():
                        nicKeys[nicId][nicParam] = value

        
        if nicKeys and len(nicKeys.keys()) >0:
            for key, vmNicMeta in nicKeys.iteritems():
                vmNicMeta['enterprise'] = enterprise
                vmNicMeta['user'] = user


                if 'l2domain' in vmNicMeta:
                    vmNicMeta['domain'] = vmNicMeta['l2domain']
                    vmNicMeta['domainType'] = 'L2'
                    vmNicMeta.pop('l2domain', None)
                else:
                    vmNicMeta['domainType'] = 'L3'

                vmMetadata.append(vmNicMeta)

    return vmMetadata

def write_to_csv(vms=None, outputfile='vm_metadata.csv'):
    if vms and len(vms)>0:
        csvWriter = csv.DictWriter(open(outputfile, mode='w'), CSV_FIELDS, extrasaction="ignore")
        #Write CSV headers
        csvWriter.writeheader()

        for vm, vmInfo in vms.iteritems():
            (vmUUID, vmName, vmMetadatas) = vmInfo

            if vmMetadatas and len(vmMetadatas)>0:
                for metadata in vmMetadatas:
                    metadata['uuid'] = vmUUID
                    metadata['name'] = vmName
                    #print "%s" % (metadata)
                    csvWriter.writerow(metadata)
            else:
                metadata={}
                metadata['uuid'] = vmUUID
                metadata['name'] = vmName
                csvWriter.writerow(metadata)


def get_container_view(service_instance, obj_type, container=None):
    """
    Get a vSphere Container View reference to all objects of type 'obj_type'

    It is up to the caller to take care of destroying the View when no longer
    needed.

    Args:
        obj_type (list): A list of managed object types

    Returns:
        A container view ref to the discovered managed objects

    """
    if not container:
        container = service_instance.content.rootFolder

    view_ref = service_instance.content.viewManager.CreateContainerView(
        container=container,
        type=obj_type,
        recursive=True
    )
    return view_ref

def collect_properties(service_instance, view_ref, obj_type, path_set=None, include_mors=False):
    """
    Collect properties for managed objects from a view ref

    Check the vSphere API documentation for example on retrieving
    object properties:

        - http://goo.gl/erbFDz

    Args:
        si          (ServiceInstance): ServiceInstance connection
        view_ref (pyVmomi.vim.view.*): Starting point of inventory navigation
        obj_type      (pyVmomi.vim.*): Type of managed object
        path_set               (list): List of properties to retrieve
        include_mors           (bool): If True include the managed objects
                                       refs in the result

    Returns:
        A list of properties for the managed objects

    """
    collector = service_instance.content.propertyCollector

    # Create object specification to define the starting point of
    # inventory navigation
    obj_spec = vmodl.query.PropertyCollector.ObjectSpec()
    obj_spec.obj = view_ref
    obj_spec.skip = True

    # Create a traversal specification to identify the path for collection
    traversal_spec = vmodl.query.PropertyCollector.TraversalSpec()
    traversal_spec.name = 'traverseEntities'
    traversal_spec.path = 'view'
    traversal_spec.skip = False
    traversal_spec.type = view_ref.__class__
    obj_spec.selectSet = [traversal_spec]

    # Identify the properties to the retrieved
    property_spec = vmodl.query.PropertyCollector.PropertySpec()
    property_spec.type = obj_type

    if not path_set:
        property_spec.all = True

    property_spec.pathSet = path_set

    # Add the object and property specification to the
    # property filter specification
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [property_spec]

    # Retrieve properties
    props = collector.RetrieveContents([filter_spec])

    data = []
    for obj in props:
        properties = {}
        for prop in obj.propSet:
            properties[prop.name] = prop.val

        if include_mors:
            properties['obj'] = obj.obj

        data.append(properties)
    return data


def main(vmNameFilter, enterpriseFilter, domainFilter, zoneFilter, subnetFilter):
    if config and config.vCenter:
        service_instance = None
        try:
            logger.info('Connecting to vCenter %s' % (config.vCenter['host']) )
            logger.debug('Connection settings: %s' % (config.vCenter) )

            service_instance = connect.SmartConnect(host=config.vCenter['host'],
                                                    user=config.vCenter['user'],
                                                    pwd=config.vCenter['password'],
                                                    port=int(config.vCenter['port']))

        except Exception as exc:
            if '[SSL: CERTIFICATE_VERIFY_FAILED]' in '%s' % (exc):
                logger.debug('SSL Connection to vCenter required')
                try:
                    import ssl
                    default_context = ssl._create_default_https_context
                    ssl._create_default_https_context = ssl._create_unverified_context
                    service_instance = connect.SmartConnect(host=config.vCenter['host'],
                                                        user=config.vCenter['user'],
                                                        pwd=config.vCenter['password'],
                                                        port=int(config.vCenter['port']))
                    ssl._create_default_https_context = default_context
                except Exception as exc1:
                    logger.debug('Error while connecting to vCenter, %s' % (exc1))
                    raise Exception(exc1)
            else:
                logger.debug('Error while connecting to vCenter, %s' % (exc1))
                raise Exception(exc)


        try:
            logger.debug('Connected to vCenter: %s' % (config.vCenter['host']) )

            atexit.register(connect.Disconnect, service_instance)

            logger.debug('Creating view on VirtualMachine objects')
            root_folder = service_instance.content.rootFolder
            view = get_container_view(service_instance,
                                               obj_type=[vim.VirtualMachine])

            logger.info('Collecting VirtualMachine(s) raw information')
            vm_data = collect_properties(service_instance, view_ref=view,
                                                  obj_type=vim.VirtualMachine,
                                                  path_set=vm_properties,
                                                  include_mors=True)
            logger.info('%s VirtualMachine(s) found' % (len(vm_data)))


            vmsNuageMetaData = {}
            for vm in vm_data:
                vmName = vm["name"]
                vmUUID = vm["config.uuid"]
                vmMetadata = getNuageMetaData(vm["config.extraConfig"])
                logger.debug('Parsing VM raw info: name=%s uuid=%s metadata=%s' % (vmName, vmUUID, vmMetadata) )

                #Check VM name against filter
                if not (( vmNameFilter.strip() == '') or (vmNameFilter.lower() in vmName.lower() )):
                    logger.debug('Discarding VM: name=%s uuid=%s metadata=%s' % (vmName, vmUUID, vmMetadata) )
                    continue

                logger.debug('Adding VM: name=%s uuid=%s metadata=%s' % (vmName, vmUUID, vmMetadata) )
                vmsNuageMetaData[vmUUID] = (vmUUID, vmName, vmMetadata)


            logger.info('Num. of VM collected: %s' % (len(vmsNuageMetaData)) )
            logger.debug('%s' % (vmsNuageMetaData) )

            logger.info('Generating CSV file')
            write_to_csv(vmsNuageMetaData)

        except Exception as exc:
            print("Exception:\n %s" % (exc) )
            pass


# def print_info(*objs):
#     print(*objs, file=sys.stderr)


def printHelp(argvs):
    helpString = "\n"
    helpString += " SYNOPSIS\n"
    helpString += "    %s filter [OPTIONS]\n" % argvs[0]
    helpString += "\n"
    helpString += " DESCRIPTION\n"
    helpString += "    This script will search for vPorts with name or description matching the filter.\n"
    helpString += "\n"
    helpString += " OPTIONS\n"
    helpString += "    -h, --help         Print this help\n"
    helpString += "    -v, --version      Print this version\n"
    helpString += "    -o, --output       Output the result to a csv file\n"
    helpString += "    -e, --enterprise   Filter on Enterprise name\n"
    helpString += "    -d, --domain       Filter on Domain name\n"
    helpString += "    -z, --zone         Filter on Zone name\n"
    helpString += "    -s, --sunet        Filter on Subnet name\n"
    helpString += "\n"

    return helpString



# Start program
if __name__ == "__main__":

    try:
        opts, args = getopt.getopt(sys.argv[1:], "vhno:e:d:z:s:", ["help","debug","name=", "enterprise=","domain=", "zone=", "subnet="])
    except getopt.GetoptError:
        #print_info(printHelp(argvs))
        sys.exit(2)


    vmNameFilter = ''
    enterpriseFilter = ''
    domainFilter = ''
    zoneFilter = ''
    subnetFilter = ''


    for opt, arg in opts:
        
        if opt in ("-h", "--help"):
            print_info(printHelp(argvs))
            sys.exit()

        elif opt in ("-n", "--name"):
            vmNameFilter = arg

        elif opt in ("-v", "--debug"):
            print "Set Logging level to DEBUG"
            logger.setLevel(logging.DEBUG)

        elif opt in ("-e"):
            enterprisefilter = "%s" % (arg)
        elif opt in ("-d"):
            domainfilter = "%s" % (arg)
        elif opt in ("-z"):
            zonefilter = "%s" % (arg)
        elif opt in ("-s"):
            subnetfilter = "%s" % (arg)

        elif opt in ("--enterprise"):
            enterprisefilter = "%s" % (arg)
        elif opt in ("--domain"):
            domainfilter = "%s" % (arg)
        elif opt in ("--zone"):
            zonefilter = "%s" % (arg)

    logger.debug( "VM name filter: %s" % vmNameFilter )
    logger.debug( "Enterprise Filter: %s" % enterpriseFilter )
    logger.debug( "Domain Filter: %s" % domainFilter )
    logger.debug( "Zone Filter: %s" % zoneFilter )
    logger.debug( "Subnet Filter: %s" % subnetFilter )

    main(vmNameFilter, enterpriseFilter, domainFilter, zoneFilter, subnetFilter)
