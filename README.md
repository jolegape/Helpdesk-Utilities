
# Helpdesk-Utilities
Helpdesk Utilities is a collection of python scripts used to automate data syncing and sharing between Active Directory/LDAP, [osTicket](https://osticket.com/), and [Snipe-IT](https://snipeitapp.com/). While Snipe-IT and osTicket both have native LDAP support, I use this to better format the data in a way that suits my environment. E.g. In osTicket, I like the name of the user in the ticket to display as First Last (EMPLOYEEID) (YEAR), where YEAR = the student year level (if a student), or STAFF if a staff member.
```
![Alt text](/Screenshots/TicketNameExample.png?raw=true "osTicket Name Example")
```
Long term this will be turned into a docker app, hence the use of a .env file at the moment. 

## Getting Started

This assumes you have python installed. Download or clone the package to your desired location and run.

    pip install -r requirements.txt

Most settings are configured through environment variables. Edit the .env file supplied to reflect your environment. 

    # SnipeIT Configuration
    SNIPEIT_URL = https://snipeit.example.com
    SNIPEIT_TOKEN = APIKEYGOESHERE

The Snipe-IT settings should be self explanatory. Provide your Snipe-IT URL, and the API key of a user with permissions to add/edit/delete records. For my implementation I use the default admin account, secured with a random password.
    
    # osTicket Configuration
    OST_DB_HOST = 192.168.1.1
    OST_DB_NAME = osticket
    OST_DB_USER = osticket_db_user
    OST_DB_PASS = osticket_db_pass
    OST_DB_PORT = 3306

Due to an absence of an osTicket API, the `syncUsers.py` script modifies the osTicket database directly. The osTicket username and password should have read/write permissions to the osTicket database. For my implementation I used the credentials created with the initial osTicket installation. OST_DB_PORT is optional. If it doesn't exist it will use the default port of 3306. This setting is provided if you use a different port number.
     
    # LDAP Configuration
    LDAP_SERVER = 'example.com'
    LDAP_BIND_USER = ''
    LDAP_BIND_PASS = 'LDAPBINDPASSWORD'
    LDAP_SEARCH_BASE = 'OU=Automated Objects,DC=example,DC=com'
    LDAP_SEARCH_FILTER = '(&(objectClass=user)(|(memberOf:1.2.840.113556.1.4.1941:=CN=IM_STAFF_971_ALL,OU=Staff Groups,OU=SMC,OU=Automated Objects,DC=example,DC=com)(memberOf:1.2.840.113556.1.4.1941:=CN=IM_STUDENT_971_ALL,OU=Student Groups,OU=SMC,OU=Automated Objects,DC=example,DC=com)))'
 
Provide the LDAP bind user in DN form. e.g.: 

> 'CN=Helpdesk Utilities,OU=Service Accounts,OU=Resources,DC=example,DC=com'

LDAP Search base needs to be set to the root directory of the users you want to search for. In my case, all users have a parent OU of Automated Objects. The search filter can be used to narrow down the users further. My AD server comprises data from 30 schools. In this case I only wanted to target users from the school that I support. The example filter will get users from the following AD groups:

 - IM_STAFF_971_ALL
 - IM_STUDENT_971_ALL

For further information on the LDAP search filter syntax, see the Microsoft Documentation [here](https://learn.microsoft.com/en-us/windows/win32/adsi/search-filter-syntax). For further information on LDAP configuration, refer to the ldap3 project documentation [here](https://ldap3.readthedocs.io/en/latest/)

**osTicket Configuration**
The only other settings that need to be changed are in the `syncDevices.py` file. 

First, [create a list](https://docs.osticket.com/en/latest/Admin/Manage/Lists.html) in osTicket. I named mine **Asset**. In the properties tab, define the following Item Properties and press Save Changes:
| **Label**    | **Type**     | **Visibility**                | **Variable** |
|--------------|--------------|-------------------------------|--------------|
| Snipe ID     | Short Answer | Internal, Required, Immutable | snipeID      |
| Manufacturer | Short Answer | Required, Immutable           | manufacturer |
| Model        | Short Answer | Required, Immutable           | model        |
| Status       | Short Answer | Internal, Required, Immutable | status       |
| Service Tag  | Short Answer | Required, Immutable           | serviceTag   |
| Asset Number | Short Answer | Required                      | assetNumber  |
| Type         | Short Answer | Internal, Optional            | itemType     |
```
![Alt text](/Screenshots/ListDefinition.png?raw=true "osTicket List Definition")
```
```
![Alt text](/Screenshots/ListProperties.png?raw=true "osTicket List Properties")
```
Once this has been completed, go into the list and use the id value in the URL to update line 23. In my case, the asset list had an ID of 3. 
```
![Alt text](/Screenshots/ListID.png?raw=true "osTicket List ID")
```
Go to the List Properties tab, and hover over the Config button for each property. Use the number at the end of the displayed URL to update the relevant property for lines 25-31.
```
![Alt text](/Screenshots/ListPropertiesID.png?raw=true "osTicket List Properties ID")
```

Once the configuration is completed you should be able to run `python syncDevices.py` or `python syncUsers.py` . If all is correct you should see users appear in Snipe-IT and osTicket, and devices populate the osTicket list that you created.
**Snipe-IT Users**
```
![Alt text](/Screenshots/Snipe-ITUsers.png?raw=true "Snipe-IT Users")
```
**osTicket Users**
```
![Alt text](/Screenshots/osTicketUsers.png?raw=true "osTicket Users")
```
**osTicket Devices**
```
![Alt text](/Screenshots/ListItems.png?raw=true "osTicket List Items")
```
To use the lists in a helpdesk ticket, create a form with a field targeting the Asset list. In the following example I target the same list twice. Once to record the asset being repaired, and the second time to record the replacement asset handed to the user. 
```
![Alt text](/Screenshots/FormFieldsExample.png?raw=true "osTicket Form Fields")
```
For both fields I set the widget to TypeAhead. This allows me to enter or scan are barcode and have it search, rather than displaying a list with 1000's of devices.
```
![Alt text](/Screenshots/FormFieldsSetup.png?raw=true "Form Fields Setup")
```
```
![Alt text](/Screenshots/FormFieldsSettings.png?raw=true "Form Fields Settings")
```

Once this is done, you should be able to target devices when creating a ticket.
```
![Alt text](/Screenshots/NewTicketExample.png?raw=true "New Ticket Example")
```


## Acknowledgements
This project began as the brain child of my former colleague Paul. Without his help and guidance I would not have had the inspiration to develop this into what it is now.