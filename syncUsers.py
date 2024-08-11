import requests
from ratelimit import limits, sleep_and_retry
from deepdiff import DeepDiff
import pymysql
import os
import ldap3
import json
import html
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# LDAP Configuration
LDAP_SERVER = os.getenv('LDAP_SERVER')
LDAP_BIND_USER = os.getenv('LDAP_BIND_USER')
LDAP_BIND_PASS = os.getenv('LDAP_BIND_PASS')
LDAP_SEARCH_BASE = os.getenv('LDAP_SEARCH_BASE')
LDAP_SEARCH_FILTER = os.getenv('LDAP_SEARCH_FILTER')
LDAP_ATTRIBUTES = ['givenName', 'sn', 'sAMAccountName', 'mail', 'extensionAttribute1', 'employeeType', 'employeeID', 'title', 'distinguishedname', 'cn']

# OSTicket Configuration
OSTICKET_DB_HOST = os.getenv('OST_DB_HOST')
OSTICKET_DB_NAME = os.getenv('OST_DB_NAME')
OSTICKET_DB_USER = os.getenv('OST_DB_USER')
OSTICKET_DB_PASS = os.getenv('OST_DB_PASS')
OSTICKET_DB_PORT = os.getenv('OST_DB_PORT', 3306) # Default to Port 3306 if not specified
OST_CONTACT_FORM_ID = 1

# SnipeIT Configuration
SNIPEIT_URL = os.getenv('SNIPEIT_URL')
SNIPEIT_API = SNIPEIT_URL + '/api/v1'
SNIPEIT_TOKEN = os.getenv('SNIPEIT_TOKEN')
SNIPEIT_HEADERS = {'Authorization': f'Bearer {SNIPEIT_TOKEN}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
SNIPE_IGNORED_USERNAMES = ['administrator', 'sccm']

def get_ldapUsers():

    server = ldap3.Server(LDAP_SERVER)
    conn = ldap3.Connection(server=server, user=LDAP_BIND_USER, password=LDAP_BIND_PASS)
    conn.bind()
    conn.search(search_base=LDAP_SEARCH_BASE, search_filter=LDAP_SEARCH_FILTER, search_scope=ldap3.SUBTREE, attributes=LDAP_ATTRIBUTES)

    ldapUsers = {}

    for result in conn.response:
        ldapUser = {
            'mail': result['attributes']['mail'],
            'givenName': result['attributes']['givenName'].title(),
            'sn': result['attributes']['sn'].title(),
            'sAMAccountName': result['attributes']['sAMAccountName'].lower(),
            'extensionAttribute1': result['attributes']['extensionAttribute1'],
            'employeeType': result['attributes']['employeeType'],
            'employeeID': result['attributes']['employeeID'],
            'title': result['attributes']['title'],
            'dn': result['attributes']['distinguishedName'],
            'cn': result['attributes']['cn'],

        }

        # If student, extensionAttribute1 = Year Level, else equals employeeType
        if result['attributes']['employeeType'] == 'STUDENT':
            ldapUser['extensionAttribute1'] = '{}'.format(result['attributes']['extensionAttribute1'].zfill(2))
        else:
            ldapUser['extensionAttribute1'] = result['attributes']['employeeType']

        ldapUser['ost_cn'] = f"{result['attributes']['cn']} ({ldapUser['extensionAttribute1']})"  

        ldapUsers[ldapUser['employeeID'].lower()] = ldapUser
    
    return ldapUsers

def get_ostUsers():

    ostUsers = {}

    with dbConn.cursor() as cursor:
        sqlCommand = """
            SELECT ost_user.id AS ost_user_id,
            ost_user.name,
            ost_user.default_email_id AS ost_user_email_id,
            ost_user_email.address,
            ost_form_entry.id AS ost_form_entry_id,
            ost_user_account.username AS ost_user_account_username,
            ost_user_account.status,
            CONCAT('{',GROUP_CONCAT(CONCAT('"',ost_form_entry_values.field_id,'": "', ost_form_entry_values.value,'"')), '}') AS ost_form_values
            FROM ost_user
            INNER JOIN ost_user_email on ost_user.id = ost_user_email.user_id
            INNER JOIN ost_form_entry on ost_user.id = ost_form_entry.object_id AND ost_form_entry.object_type = 'U' AND ost_form_entry.form_id = 1
            INNER JOIN ost_form_entry_values on ost_form_entry.id = ost_form_entry_values.entry_id
            INNER JOIN ost_user_account ON ost_user.id = ost_user_account.user_id
            GROUP BY ost_user.id
        """
        cursor.execute(sqlCommand)

        for row in cursor.fetchall():
            ldapData = json.loads(row[7])
            ostUser = {
                'mail': row[3],
                'sAMAccountName': row[5],
                'extensionAttribute1':ldapData['53'],
                'employeeID': ldapData['52'],
                'title': ldapData['54'],
                'dn': ldapData['51'],
                'ost_cn': row[1],
                'ost_user_id': row[0],
                'ost_email_id': row[2],
                'ost_form_entry_id': row[4],
                'ost_user_status': row[6]
            }
            ostUsers[ostUser['employeeID'].lower()] = ostUser
    return ostUsers

def create_ostUser(**kwargs):

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    extra = {"browser_lang": "en_GB"}
    search_content = f"{kwargs['mail']} {kwargs['employeeID']}"
    
    with dbConn.cursor() as cursor:
        
        # Create user account in ost_user
        sqlCommand = """
            INSERT INTO ost_user (org_id, default_email_id, status, name, created, updated)
            VALUES (2, 0, 0, %s, %s, %s)
        """
        cursor.execute(sqlCommand, (kwargs['ost_cn'], now, now))
        ost_user_id = cursor.lastrowid

        # Convert account from guest to registered
        sqlCommand = """
            INSERT INTO ost_user_account (user_id, status, timezone, lang, username, passwd, backend, extra, registered)
            VALUES (%s, 9, "Australia/Brisbane", NULL, %s, NULL, "ldap.client", %s, %s)
        """
        cursor.execute(sqlCommand, (ost_user_id, kwargs['sAMAccountName'], json.dumps(extra), now))

        # Add email address to ost_user_email
        sqlCommand = """
            INSERT INTO ost_user_email (user_id, flags, address)
            VALUES (%s, 0, %s)
        """
        cursor.execute(sqlCommand, (ost_user_id, kwargs['mail']))
        ost_user_email_id = cursor.lastrowid

        # Update user entry to point to the correct ost_user_email entry
        sqlCommand = """
            UPDATE ost_user
            SET default_email_id = %s
            WHERE id = %s
        """
        cursor.execute(sqlCommand, (ost_user_email_id, ost_user_id))

        # Add user ActiveDirectory info into ost_form_entry and ost_form_entry_values. Form field ID's are hard coded.
        sqlCommand = """
            INSERT INTO ost_form_entry (form_id, object_id, object_type, sort, extra, created, updated)
            VALUES (%s, %s, "U", 1, NULL, %s, %s)
        """
        cursor.execute(sqlCommand, (OST_CONTACT_FORM_ID, ost_user_id, now, now))
        ost_form_entry_id = cursor.lastrowid

        for field_id, value in ((51, kwargs['dn']), (52, kwargs['employeeID']), (53, kwargs['extensionAttribute1']), (54, kwargs['title'])):
            sqlCommand = """
                INSERT INTO ost_form_entry_values (entry_id, field_id, value)
                VALUES (%s, %s, %s)
            """
            cursor.execute(sqlCommand, (ost_form_entry_id, field_id, value))
        
        # Add the search record to ost__search
        sqlCommand = """
            INSERT INTO ost__search (object_type, object_id, title, content)
            VALUES ("U", %s, %s, %s)
        """
        cursor.execute(sqlCommand, (ost_user_id, kwargs['ost_cn'], search_content))
    
    # Commit changes to DB
    dbConn.commit()


def update_ostUser(**kwargs):
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    extra = {"browser_lang": "en_GB"}
    search_content = f"{kwargs['mail']} {kwargs['employeeID']}"

    with dbConn.cursor() as cursor:
        
        # Update user account in ost_users
        sqlCommand = """
            UPDATE ost_user
            SET name = %s, updated = %s
            WHERE id = %s
        """
        cursor.execute(sqlCommand, (kwargs['ost_cn'], now, kwargs['ost_user_id']))

        # Update user registration in ost_user_account
        sqlCommand = """
            UPDATE ost_user_account
            SET username = %s, status = 9
            WHERE user_id = %s
        """
        cursor.execute(sqlCommand, (kwargs['sAMAccountName'], kwargs['ost_user_id']))

        # Update user email address in ost_user_email
        sqlCommand = """
            UPDATE ost_user_email
            SET address = %s
            WHERE user_id = %s
        """
        cursor.execute(sqlCommand, (kwargs['mail'], kwargs['ost_user_id']))

        # Update ost_form_entry and ost_form_entry_values. Form field ID's are hard coded.
        sqlCommand = """
            UPDATE ost_form_entry
            SET updated = %s
            WHERE form_id = %s AND object_id = %s AND object_type = "U"
        """
        cursor.execute(sqlCommand, (now, OST_CONTACT_FORM_ID, kwargs['ost_user_id']))

        for field_id, value in ((51, kwargs['dn']), (52, kwargs['employeeID']), (53, kwargs['extensionAttribute1']), (54, kwargs['title'])):
            sqlCommand = """
                SELECT *
                FROM ost_form_entry_values
                WHERE entry_id = %s AND field_id = %s
            """
            if cursor.execute(sqlCommand, (kwargs['ost_form_entry_id'], field_id)):
                sqlCommand = """
                    UPDATE ost_form_entry_values
                    SET value = %s
                    WHERE entry_id = %s AND field_id = %s
                """
                cursor.execute(sqlCommand, (value, kwargs['ost_form_entry_id'], field_id))
            else:
                sqlCommand = """
                    INSERT INTO ost_form_entry_values (entry_id, field_id, value)
                    VALUES (%s, %s, %s)
                """
                cursor.execute(sqlCommand, (kwargs['ost_form_entry_id'], field_id, value))
        
        # Update ost__search
        sqlCommand = """
            UPDATE ost__search
            SET title = %s, content = %s
            WHERE object_type = "U" AND object_id = %s
        """
        cursor.execute(sqlCommand, (kwargs['ost_cn'], search_content, kwargs['ost_user_id']))
    
    # Commit changes to DB
    dbConn.commit()


def disable_ostUser(**kwargs):
    
    with dbConn.cursor() as cursor:

        # Disable user in ost_user_account
        sqlCommand = """
            UPDATE ost_user_account
            SET status = 11
            WHERE user_id = %s
        """
        cursor.execute(sqlCommand, (kwargs['ost_user_id']))
    
    dbConn.commit()

@sleep_and_retry
@limits(calls=120, period=60)
def get_snipeUsers():
    
    snipeUsers = {}
    offset = 0
    count = 0

    r = requests.get(f'{SNIPEIT_API}/users?limit=50&offset={offset}&sort=last_name&order=asc&all=true', headers=SNIPEIT_HEADERS)
    totalUsers = r.json()['total']

    if totalUsers:
        for offset in range(0, totalUsers, 50):
            r = requests.get(f'{SNIPEIT_API}/users?limit=50&offset={offset}&sort=last_name&order=asc&all=true', headers=SNIPEIT_HEADERS)
            for user in r.json()['rows']:
                # if user['username'] == 'administrator':
                if user['username'] in SNIPE_IGNORED_USERNAMES:
                    # Ignore default administrator account
                    continue
                else:
                    snipeUser = {
                        'givenName': html.unescape(user['first_name']),
                        'sn': html.unescape(user['last_name']),
                        'sAMAccountName': user['username'],
                        'mail': user['email'],
                        'employeeID': user['employee_num'],
                        'title': html.unescape(user['jobtitle']),
                        'id': user['id'],
                        'activated': user['activated'],
                    }
                    snipeUsers[snipeUser['employeeID'].lower()] = snipeUser
                    count += 1
    
    return snipeUsers

@sleep_and_retry
@limits(calls=120, period=60)
def get_snipeDepartments():

    snipeDepartments = {}
    offset = 0
    count = 0
    
    r = requests.get(f'{SNIPEIT_API}/departments?limit=50&offset={offset}', headers=SNIPEIT_HEADERS)
    totalDepartments = r.json()['total']

    if totalDepartments:
        for offset in range(0, totalDepartments, 50):
            r = requests.get(f'{SNIPEIT_API}/departments?limit=50&offset={offset}', headers=SNIPEIT_HEADERS)
            for department in r.json()['rows']:
                snipeDepartment = {
                    'name': department['name'],
                    'id': department['id']
                }
                snipeDepartments[snipeDepartment['name'].title()] = snipeDepartment
                count += 1
    
    return snipeDepartments

@sleep_and_retry
@limits(calls=60, period=60)
def create_snipeUser(departments, **kwargs):

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    payload = {
        'first_name': kwargs['givenName'],
        'last_name': kwargs['sn'],
        'username': kwargs['sAMAccountName'],
        'password': '$2y$10$rjI89x7hd2jE46kUlTIMsO8Fybih7W5FMWpoLwlyM9eLeAGxU2xYO', # Random password - users won't ever actually log into SnipeIT - so set a random one that no one will ever guess
        'password_confirmation': '$2y$10$rjI89x7hd2jE46kUlTIMsO8Fybih7W5FMWpoLwlyM9eLeAGxU2xYO', # Random password - users won't ever actually log into SnipeIT - so set a random one that no one will ever guess,
        'email': kwargs['mail'],
        'activated': 1,
        'ldap_import': 1,
        'jobtitle': kwargs['title'],
        'employee_num': kwargs['employeeID'],
        'notes': f'User created: {now}',
    }

    if kwargs['employeeType'] == 'STUDENT':
        payload['department_id'] = departments[f"Students - Year {kwargs['extensionAttribute1'].title()}"]["id"]
    else:
        payload['department_id'] = departments[kwargs['extensionAttribute1'].title()]['id']

    r = requests.post(f'{SNIPEIT_API}/users', json=payload, headers=SNIPEIT_HEADERS)
    
    if r.status_code != 200:
        print('-----------------------------------------')
        print('Error creating Snipe-IT user. Status Code:', r.status_code)
        print('-----------------------------------------')
        print()
        print(r.text)
        print()
        print(payload)

@sleep_and_retry
@limits(calls=60, period=60)
def update_snipeUser(departments, **kwargs):

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    payload = {
        'first_name': kwargs['givenName'],
        'last_name': kwargs['sn'],
        'username': kwargs['sAMAccountName'],
        'password': '$2y$10$rjI89x7hd2jE46kUlTIMsO8Fybih7W5FMWpoLwlyM9eLeAGxU2xYO', # Random password - users won't ever actually log into SnipeIT - so set a random one that no one will ever guess
        'password_confirmation': '$2y$10$rjI89x7hd2jE46kUlTIMsO8Fybih7W5FMWpoLwlyM9eLeAGxU2xYO', # Random password - users won't ever actually log into SnipeIT - so set a random one that no one will ever guess,
        'email': kwargs['mail'],
        'activated': 1,
        'ldap_import': 1,
        'jobtitle': kwargs['title'],
        'employee_num': kwargs['employeeID'],
        'notes': f'User updated: {now}',
    }

    if kwargs['employeeType'] == 'STUDENT':
        payload['department_id'] = departments[f"Students - Year {kwargs['extensionAttribute1'].title()}"]["id"]
    else:
        payload['department_id'] = departments[kwargs['extensionAttribute1'].title()]['id']

    r = requests.patch(f"{SNIPEIT_API}/users/{kwargs['id']}", json=payload, headers=SNIPEIT_HEADERS)
    
    if r.status_code != 200:
        print('-----------------------------------------')
        print('Error updating Snipe-IT user. Status Code:', r.status_code)
        print('-----------------------------------------')
        print()
        print(r.json()['error']['message'])
        print()
        print(payload)

@sleep_and_retry
@limits(calls=60, period=60)
def disable_snipeUser(departments, **kwargs):

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    payload = {
        'activated': 0,
        'notes': f'User disabled: {now}',
        'department_id': departments['Inactive Users']['id'],
        'jobtitle': 'Inactive User'
    }

    r = requests.patch(f"{SNIPEIT_API}/users/{kwargs['id']}", json=payload, headers=SNIPEIT_HEADERS)

    if r.status_code != 200:
        print('-----------------------------------------')
        print('Error disabling Snipe-IT user. Status Code:', r.status_code)
        print('-----------------------------------------')
        print()
        print(r.json()['error']['message'])
        print()
        print(payload)


if __name__ == '__main__':

    dbConn = pymysql.connect(
        host=OSTICKET_DB_HOST,
        port=int(OSTICKET_DB_PORT),
        user=OSTICKET_DB_USER,
        passwd=OSTICKET_DB_PASS,
        db=OSTICKET_DB_NAME
    )

    ldapUsers = get_ldapUsers()
    ostUsers = get_ostUsers()
    snipeUsers = get_snipeUsers()
    snipeDepartments = get_snipeDepartments()
    
    # Create / update users
    for employeeID, ldapUser in ldapUsers.items():
        
        # # osTicket
        if employeeID in ostUsers.keys():
            userDiff = DeepDiff(ostUsers[employeeID], ldapUsers[employeeID], ignore_string_case=True, ignore_order=True, exclude_paths=["ost_user_id", "ost_email_id", "ost_form_entry_id", "ost_user_status", "givenName", "sn", "employeeType"])
            existingUser = ostUsers[employeeID]
            existingUser.update(ldapUser)
            if 'values_changed' in userDiff or ostUsers[employeeID]['ost_user_status'] == 11:
                print(f'Updating osTicket user account for {employeeID}...')
                update_ostUser(**existingUser)
        else:
            print(f'Creating osTicket user account for {employeeID}...')
            create_ostUser(**ldapUser)
        
        # Snipe-IT
        if employeeID in snipeUsers.keys():
            userDiff = DeepDiff(snipeUsers[employeeID], ldapUsers[employeeID], ignore_string_case=True, ignore_order=True, exclude_paths=["extensionAttribute1", "employeeType", "dn", "ost_cn"])
            existingUser = snipeUsers[employeeID]
            existingUser.update(ldapUser)
            if 'values_changed' in userDiff or snipeUsers[employeeID]['activated'] == False:
                print(f'Updating Snipe-IT user account for {employeeID}...')
                update_snipeUser(snipeDepartments, **existingUser)
        else:
            print(f'Creating Snipe-IT user account for {employeeID}...')
            create_snipeUser(snipeDepartments, **ldapUser)
    
    # Disable osTicket accounts if matching account not found in ldap data.
    for employeeID, ostUser in ostUsers.items():
        if ldapUsers.get(employeeID, None) == None and ostUser['ost_user_status'] == 9:
            print(f'{employeeID} does not exist in AD anymore. Disabling account in osTicket...')
            disable_ostUser(**ostUser)
    
    # Disable snipeIT accounts if matching accoun not found in ldap data.
    for employeeID, snipeUser in snipeUsers.items():
        if ldapUsers.get(employeeID, None) == None and snipeUser['activated'] == True:
            print(f'{employeeID} does not exist in AD anymore. Disabling account in Snipe-IT...')
            disable_snipeUser(snipeDepartments, **snipeUser)