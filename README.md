# VMWare_MetaData

Connection information to vCenter is defined in config.py


## Usage

### getVmMetaData.py
Retrieve all the VMs in vCenter and collect Nuage Metadata if present, and generate a csv file called **vm_metadata.csv**.


### setVmMetaData.py
Set the metadatas to the VMs defined in the file **vm_metadata.csv**



## Notes

### vm_metadata.csv format
**Fields**:

- **uuid**       VM UUID
- **name**       VM name
- **nic**        VM network interface (nic[0-9])
- **user**       Nuage user
- **enterprise** Nuage enterprise name
- **domain**     Nuage domain name
- **zone**       Nuage zone name
- **network**    Nuage subnet name
- **networktype**  has to be ipv4
- **ip**         Static IP 
- **policy-group**  Policy Group to be assigned to Nuage vPort
- **redirection-target** Redirection Target to be assigned to Nuage vPort

**Example**:

uuid,name,nic,user,enterprise,domain,zone,network,networktype,ip,policy-group,redirection-target
42250baa-4b98-1532-fccc-9f1ecb66efd4,NuageVM-184-01,nic0,user001,enterprise001,domain001,zone001,subnet001,ipv4,,,
42250baa-4b98-1532-fccc-9f1ecb66efd4,NuageVM-184-01,nic1,user001,enterprise001,domain001,Zone 31,Subnet 3,ipv4,,,
4225047c-627e-a583-8e24-407ce829f1d3,NuageVM-184-02,nic0,user001,Lab04,Domain001,Zone 3,Subnet 3,ipv4,,,
