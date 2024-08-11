import pymysql
import os
import json
import requests
from ratelimit import limits, sleep_and_retry
from deepdiff import DeepDiff

from dotenv import load_dotenv
load_dotenv()

# SnipeIT Configuration
SNIPEIT_URL = os.getenv('SNIPEIT_URL')
SNIPEIT_API = SNIPEIT_URL + '/api/v1'
SNIPEIT_TOKEN = os.getenv('SNIPEIT_TOKEN')
SNIPEIT_HEADERS = {'Authorization': f'Bearer {SNIPEIT_TOKEN}', 'Accept': 'application/json', 'Content-Type': 'application/json'}

# OSTicket Configuration
OSTICKET_DB_HOST = os.getenv('OST_DB_HOST')
OSTICKET_DB_NAME = os.getenv('OST_DB_NAME')
OSTICKET_DB_USER = os.getenv('OST_DB_USER')
OSTICKET_DB_PASS = os.getenv('OST_DB_PASS')
OSTICKET_DB_PORT = os.getenv('OST_DB_PORT', 3306) # Default to Port 3306 if not specified
OSTICKET_ASSET_LIST_ID = 3
OSTICKET_ASSET_FIELD_IDS = {
    'snipeID': 42,
    'manufacturer': 43,
    'model': 44,
    'status': 45,
    'serviceTag': 46,
    'assetTag': 47,
    'itemType': 48
}
OSTICKET_REVERSE_ASSET_FIELD_IDS = dict([(v, k) for k, v in OSTICKET_ASSET_FIELD_IDS.items()])

def dbConn():
    dbConn = pymysql.connect(
        host=OSTICKET_DB_HOST,
        port=int(OSTICKET_DB_PORT),
        user=OSTICKET_DB_USER,
        passwd=OSTICKET_DB_PASS,
        db=OSTICKET_DB_NAME
    )
    return dbConn

@sleep_and_retry
@limits(calls=120, period=60)
def get_snipeAssets():

    snipeAssets = {}
    offset = 0
    count = 0

    r = requests.get(f'{SNIPEIT_API}/hardware?limit=50&offset={offset}', headers=SNIPEIT_HEADERS)
    totalAssets = r.json()['total']

    if totalAssets:
        for offset in range(0, totalAssets, 50):
            r = requests.get(f'{SNIPEIT_API}/hardware?limit=50&offset={offset}', headers=SNIPEIT_HEADERS)
            for asset in r.json()['rows']:
                snipeAsset = {
                    'snipeID': asset['id'],
                    'manufacturer': asset['manufacturer']['name'],
                    'model': asset['model']['name'],
                    'status': asset['status_label']['name'],
                    'serviceTag': asset['serial'],
                    'assetTag': asset['asset_tag'],
                    'itemType': asset['category']['name']
                }
                snipeAssets[snipeAsset['snipeID']] = snipeAsset
                count += 1
    return snipeAssets

def get_ostAssets(listID):

    ostAssets = {}

    with dbConn.cursor() as cursor:
        sqlCommand = """
            SELECT id, value, extra, properties
            FROM ost_list_items
            WHERE list_id = %s
        """
        cursor.execute(sqlCommand, (listID))

        for row in cursor.fetchall():
            assetItem = {
                'ostID': row[0],
                'value': row[1],
                'extra': row[2]
            }

            properties = json.loads(row[3])
            mappedProperties = {}
            for k, v in properties.items():
                k = int(k)
                mappedProperties[OSTICKET_REVERSE_ASSET_FIELD_IDS[k]] = v
            assetItem.update(mappedProperties)
            ostAssets[assetItem['snipeID']] = assetItem
    
    return ostAssets

def make_ostListProperties(**kwargs):
    ostListProperties = {}

    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['snipeID'])] = kwargs['snipeID']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['manufacturer'])] = kwargs['manufacturer']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['model'])] = kwargs['model']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['status'])] = kwargs['status']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['serviceTag'])] = kwargs['serviceTag']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['assetTag'])] = kwargs['assetTag']
    ostListProperties[str(OSTICKET_ASSET_FIELD_IDS['itemType'])] = kwargs['itemType']

    return ostListProperties

def generate_ostValue(**kwargs):

    # Generate ost_list_items.value field value
    if kwargs['itemType'] == 'Charger':
        value = f"{kwargs['manufacturer']} Charger: {kwargs['model']} - {kwargs['assetTag']}"
    else:
        value = f"{kwargs['model']} ({kwargs['assetTag']}) ({kwargs['serviceTag']})"
    
    return value


def create_ostAssetItem(**kwargs):
    
    value = generate_ostValue(**kwargs)
    extra = f"{kwargs['manufacturer']} {kwargs['model']}"
    properties = json.dumps(make_ostListProperties(**kwargs))

    with dbConn.cursor() as cursor:

        # Insert list item into ost_list_items
        sqlCommand = """
            INSERT INTO ost_list_items (list_id, status, value, extra, sort, properties)
            VALUES (%s, 1, %s, %s, 1, %s)
        """
        cursor.execute(sqlCommand, (OSTICKET_ASSET_LIST_ID, value, extra, properties))
    
    # Commit changes to DB
    dbConn.commit()


def update_ostAssetItem(**kwargs):

    value = generate_ostValue(**kwargs)
    extra = f"{kwargs['manufacturer']} {kwargs['model']}"
    properties = json.dumps(make_ostListProperties(**kwargs))

    with dbConn.cursor() as cursor:
        sqlCommand = """
            UPDATE ost_list_items
            SET value = %s, extra = %s, properties = %s
            WHERE id = %s
        """
        cursor.execute(sqlCommand, (value, extra, properties, kwargs['ostID']))
    
    # Commit changes to DB
    dbConn.commit()

def remove_ostAssetItem(**kwargs):

    with dbConn.cursor() as cursor:
        sqlCommand = """
            DELETE
            FROM ost_list_items
            WHERE id = %s
        """
        cursor.execute(sqlCommand, (kwargs['ostID']))
    
    # Commit changes to DB
    dbConn.commit()
    
if __name__ == '__main__':

    dbConn = pymysql.connect(
        host=OSTICKET_DB_HOST,
        port=int(OSTICKET_DB_PORT),
        user=OSTICKET_DB_USER,
        passwd=OSTICKET_DB_PASS,
        db=OSTICKET_DB_NAME
    )

    snipeAssets = get_snipeAssets()
    ostAssets = get_ostAssets(OSTICKET_ASSET_LIST_ID)

    # Create / update assets in osTicket using SnipeIT data
    for assetID, snipeITAsset in snipeAssets.items():
        if assetID in ostAssets.keys():
            assetDiff = DeepDiff(ostAssets[assetID], snipeAssets[assetID], ignore_order=True, ignore_string_case=True, exclude_paths=["ostID", "value", "extra"])
            if 'values_changed' in assetDiff:
                snipeITAsset['ostID'] = ostAssets[assetID]['ostID']
                print(f'Updating asset: {assetID}')
                update_ostAssetItem(**snipeITAsset)
        else:
            print(f"Creating asset {snipeITAsset['assetTag']}")
            # print(snipeITAsset)
            create_ostAssetItem(**snipeITAsset)

    # Remove assets from osTicket if matching locations not found in SnipeIT data
    for assetID, ostAsset in ostAssets.items():
        if snipeAssets.get(assetID, None) == None:
            print(f"Asset {assetID} does not exist in Snipe-IT anymore. Removing from osTicket...")
            remove_ostAssetItem(**ostAsset)