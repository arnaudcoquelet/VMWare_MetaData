import csv

import atexit

from pyVim import connect
from pyVmomi import vim
from pyVmomi import vmodl

#import tools.cli as cli
#import tools.pchelper as pchelper

CSV_FIELDS = ['uuid', 'name', 'nic', 'user', 'enterprise', 'domain', 'zone', 'network', 'networktype', 'ip','policy-group', 'redirection-target']
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
        csvWriter = csv.DictWriter(open(outputfile, mode='w'), CSV_FIELDS)
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


def main():
    if config and config.vCenter:
        service_instance = None
        try:
            service_instance = connect.SmartConnect(host=config.vCenter['host'],
                                                    user=config.vCenter['user'],
                                                    pwd=config.vCenter['password'],
                                                    port=int(config.vCenter['port']))

        except Exception as exc:
            if '[SSL: CERTIFICATE_VERIFY_FAILED]' in '%s' % (exc):
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
                    raise Exception(exc1)
            else:
                raise Exception(exc)


        try:
            atexit.register(connect.Disconnect, service_instance)

            root_folder = service_instance.content.rootFolder
            view = get_container_view(service_instance,
                                               obj_type=[vim.VirtualMachine])
            vm_data = collect_properties(service_instance, view_ref=view,
                                                  obj_type=vim.VirtualMachine,
                                                  path_set=vm_properties,
                                                  include_mors=True)
            vmsNuageMetaData = {}
            for vm in vm_data:
                vmName = vm["name"]
                vmUUID = vm["config.uuid"]
                vmMetadata = getNuageMetaData(vm["config.extraConfig"])

                # if args.nuage:
                #     if vmMetadata and len(vmMetadata) >0:
                #         vmsNuageMetaData[vmUUID] = (vmUUID, vmName, vmMetadata)

                # else:
                #     vmsNuageMetaData[vmUUID] = (vmUUID, vmName, vmMetadata)
                
                vmsNuageMetaData[vmUUID] = (vmUUID, vmName, vmMetadata)

            write_to_csv(vmsNuageMetaData)

        except Exception as exc:
            print("Exception:\n %s" % (exc) )
            pass

# Start program
if __name__ == "__main__":
    main()
