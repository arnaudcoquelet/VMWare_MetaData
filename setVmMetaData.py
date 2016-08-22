import csv
import traceback
import atexit

from pyVim import connect
from pyVmomi import vim
from pyVmomi import vmodl

#import tools.cli as cli
#import tools.pchelper as pchelper
#import tools.tasks as tasks

CSV_FIELDS = ['uuid', 'name', 'nic', 'user', 'enterprise', 'domainType', 'domain', 'zone', 'network', 'networktype', 'ip','policy-group', 'redirection-target']

import config as config


def wait_for_tasks(service_instance, tasks):
    """Given the service instance si and tasks, it returns after all the
   tasks are complete
   """
    property_collector = service_instance.content.propertyCollector
    task_list = [str(task) for task in tasks]
    # Create filter
    obj_specs = [vmodl.query.PropertyCollector.ObjectSpec(obj=task)
                 for task in tasks]
    property_spec = vmodl.query.PropertyCollector.PropertySpec(type=vim.Task,
                                                               pathSet=[],
                                                               all=True)
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = obj_specs
    filter_spec.propSet = [property_spec]
    pcfilter = property_collector.CreateFilter(filter_spec, True)
    try:
        version, state = None, None
        # Loop looking for updates till the state moves to a completed state.
        while len(task_list):
            update = property_collector.WaitForUpdates(version)
            for filter_set in update.filterSet:
                for obj_set in filter_set.objectSet:
                    task = obj_set.obj
                    for change in obj_set.changeSet:
                        if change.name == 'info':
                            state = change.val.state
                        elif change.name == 'info.state':
                            state = change.val
                        else:
                            continue

                        if not str(task) in task_list:
                            continue

                        if state == vim.TaskInfo.State.success:
                            # Remove task from taskList
                            task_list.remove(str(task))
                        elif state == vim.TaskInfo.State.error:
                            raise task.info.error
            # Move to next version
            version = update.version
    finally:
        if pcfilter:
            pcfilter.Destroy()


def loadNuageFromVSC(csvFile):
    VMs = {}

    if csvFile is None or csvFile=="":
        print "No CSV file"

    input_file = csv.DictReader(open(csvFile))
    for row in input_file:
        if row['uuid'] in VMs.keys():
            #Existing VM
            vm = VMs[row['uuid']]

            interface = {}
            if row['nic'] and row['nic'] != '':
                if row['domainType'] = 'L2':
                    interface = { 'l2domain' : row['domain'],
                              'networktype' : row['networktype'],
                              'policy-group' : row['policy-group'],
                              'redirection-target' : row['redirection-target']
                              }
                else:
                    interface = { 'domain' : row['domain'],
                              'zone' : row['zone'],
                              'network' : row['network'],
                              'networktype' : row['networktype'],
                              'policy-group' : row['policy-group'],
                              'redirection-target' : row['redirection-target']
                              }

                vm['interfaces'][row['nic']] = interface

        else:
            #New VM
            vm = {
                'name' : row['name'],
                'user' : row['user'],
                'enterprise' : row['enterprise'],
                'interfaces' : {}
            }

            #If NIC defined
            interface = {}
            if row['nic'] and row['nic'] != '':
                if row['domainType'] = 'L2':
                    interface = { 'l2domain' : row['domain'],
                              'networktype' : row['networktype'],
                              'policy-group' : row['policy-group'],
                              'redirection-target' : row['redirection-target']
                              }
                else:
                    interface = { 'domain' : row['domain'],
                              'zone' : row['zone'],
                              'network' : row['network'],
                              'networktype' : row['networktype'],
                              'policy-group' : row['policy-group'],
                              'redirection-target' : row['redirection-target']
                              }

                vm['interfaces'][row['nic']] = interface

            VMs[row['uuid']] = vm

    return VMs


def getOption(extraConfig, optionKey):
    optionValue = None
    if extraConfig is None:
        return None

    for option in extraConfig:
        if option is None:
            pass

        if option.key == optionKey:
            return option

    return None

def setOption(extraConfig, optionKey, optionValue):
    option = None
    if extraConfig is None:
        return None

    if optionKey is None:
        return None

    option = getOption(extraConfig, optionKey)
    if option:
        option.value = optionValue
    else:
        option = vim.option.OptionValue()
        option.key = optionKey
        option.value = optionValue
        extraConfig.append(option)

    return option


def main():

    VMs = loadNuageFromVSC("vm_metadata.csv")

    if VMs is None or len(VMs.keys()) == 0:
        print 'No VM defined'
        return 0

    print "VM(s) to process: (%s)" % ( len(VMs.keys()) )
    for key, value in VMs.iteritems():
        print "- VM %s:\n%s\n" % (key, value)


    if config and config.vCenter:
        service_instance = None
        try:
            service_instance = connect.SmartConnect(host=config.vCenter['host'],
                                                    user=config.vCenter['user'],
                                                    pwd=config.vCenter['password'],
                                                    port=int(config.vCenter['port']) )

        except Exception as exc:
            if '[SSL: CERTIFICATE_VERIFY_FAILED]' in str(exc):
                try:
                    import ssl
                    default_context = ssl._create_default_https_context
                    ssl._create_default_https_context = ssl._create_unverified_context
                    service_instance = connect.SmartConnect(host=config.vCenter['host'],
                                                        user=config.vCenter['user'],
                                                        pwd=config.vCenter['password'],
                                                        port=int(config.vCenter['port']) )
                    ssl._create_default_https_context = default_context
                except Exception as exc1:
                    raise Exception(exc1)
            else:
                print "%s" % config.vCenter
                raise Exception(exc)


        try:
            atexit.register(connect.Disconnect, service_instance)

            #For each VM to process
            for uuid, vmNuageMetaData in VMs.iteritems():
                name = vmNuageMetaData['name']

                vm = service_instance.content.searchIndex.FindByUuid(None, uuid, True)
                if not vm:
                    print "VM %s (%s) not found" % (name, uuid)

                #VM Spec for Update
                spec = vim.vm.ConfigSpec()
                # extraCfg = vm.config.extraConfig
                extraCfg = spec.extraConfig

                setOption(extraCfg, 'nuage.user', vmNuageMetaData['user'])
                setOption(extraCfg, 'nuage.enterprise', vmNuageMetaData['enterprise'])

                #Add interface metadata
                for interface, interfacedata in vmNuageMetaData['interfaces'].iteritems():
                    if interface is None or interfacedata is None or len(interfacedata.keys()) == 0:
                        print 'No interface to add'

                    for interfacedataK, interfacedataV in interfacedata.iteritems():
                        setOption(extraCfg, 'nuage.%s.%s' % (interface, interfacedataK), interfacedataV)

                print "Updating VM %s (%s) configuration" % (name, uuid)
                #task = vm.ReconfigVM_Task(vm.config)
                task = vm.ReconfigVM_Task(spec)
                taskList.append(task)

            wait_for_tasks(service_instance, taskList)
            print "VM(s) update completed"

        except Exception as exc:
            top = traceback.extract_stack()[-1]
            print("Exception:\n %s" % (exc) )
            print("%s , %s" % (top[0], top[1]) )
            pass

# Start program
if __name__ == "__main__":
    main()
