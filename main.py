import requests
import re
import struct
import json
import argparse
import os
import pokemon_pb2
import time

from google.protobuf.internal import encoder

from datetime import datetime
from geopy.geocoders import GoogleV3
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from s2sphere import *

def encode(cellid):
    output = []
    encoder._VarintEncoder()(output.append, cellid)
    return ''.join(output)

def getNeighbors():
    origin = CellId.from_lat_lng(LatLng.from_degrees(FLOAT_LAT, FLOAT_LONG)).parent(15)
    walk = [origin.id()]
    # 10 before and 10 after
    next = origin.next()
    prev = origin.prev()
    for i in range(10):
        walk.append(prev.id())
        walk.append(next.id())
        next = next.next()
        prev = prev.prev()
    return walk



API_URL = 'https://pgorelease.nianticlabs.com/plfe/rpc'
LOGIN_URL = 'https://sso.pokemon.com/sso/login?service=https%3A%2F%2Fsso.pokemon.com%2Fsso%2Foauth2.0%2FcallbackAuthorize'
LOGIN_OAUTH = 'https://sso.pokemon.com/sso/oauth2.0/accessToken'

SESSION = requests.session()
SESSION.headers.update({'User-Agent': 'Niantic App'})
SESSION.verify = False

DEBUG = False
COORDS_LATITUDE = 0
COORDS_LONGITUDE = 0
COORDS_ALTITUDE = 0
FLOAT_LAT = 0
FLOAT_LONG = 0
deflat, deflng = 0, 0
default_step = 0.001

NUM_STEPS = 5
DATA_FILE = 'data.json'
DATA = {}

def f2i(float):
  return struct.unpack('<Q', struct.pack('<d', float))[0]

def f2h(float):
  return hex(struct.unpack('<Q', struct.pack('<d', float))[0])

def h2f(hex):
  return struct.unpack('<d', struct.pack('<Q', int(hex,16)))[0]

def prune():
    # prune despawned pokemon
    cur_time = time.time()
    for (pokehash, poke) in DATA.items():
        poke['timestamp'] = cur_time
        if poke['expiry'] <= cur_time:
            del DATA[pokehash]

try:
    with open(DATA_FILE, 'r') as f:
        DATA = json.load(f)
except:
    pass

def write_data_to_file():
    prune()

    with open(DATA_FILE + ".new", 'w') as f:
        json.dump(DATA, f, indent=2)
    os.rename(DATA_FILE + ".new", DATA_FILE);

def add_pokemon(pokeId, name, lat, lng, timestamp, timeleft):
    expiry = timestamp + timeleft
    pokehash = '%s:%s:%s' % (lat, lng, pokeId)
    if pokehash in DATA:
        if abs(DATA[pokehash]['expiry'] - expiry) < 2:
            # Assume it's the same one and average the expiry time
            DATA[pokehash]['expiry'] += expiry
            DATA[pokehash]['expiry'] /= 2
        else:
            print('[-] Two %s at the same location (%s,%s)' % (name, lat, lng))
            DATA[pokehash]['expiry'] = max(DATA[pokehash]['expiry'], expiry)
    else:
        DATA[pokehash] = {
            'id': pokeId,
            'name': name,
            'lat': lat,
            'lng': lng,
            'timestamp': timestamp,
            'expiry': expiry
        }

def set_location(location_name):
    geolocator = GoogleV3()
    loc = geolocator.geocode(location_name)

    print('[!] Your given location: {}'.format(loc.address.encode('utf-8')))
    print('[!] lat/long/alt: {} {} {}'.format(loc.latitude, loc.longitude, loc.altitude))

    global deflat
    global deflng
    deflat, deflng = loc.latitude, loc.longitude

    set_location_coords(loc.latitude, loc.longitude, loc.altitude)

def set_location_coords(lat, long, alt):
    global COORDS_LATITUDE, COORDS_LONGITUDE, COORDS_ALTITUDE
    global FLOAT_LAT, FLOAT_LONG
    FLOAT_LAT = lat
    FLOAT_LONG = long
    COORDS_LATITUDE = f2i(lat) # 0x4042bd7c00000000 # f2i(lat)
    COORDS_LONGITUDE = f2i(long) # 0xc05e8aae40000000 #f2i(long)
    COORDS_ALTITUDE = f2i(alt)

def get_location_coords():
    return (COORDS_LATITUDE, COORDS_LONGITUDE, COORDS_ALTITUDE)

def api_req(api_endpoint, access_token, *mehs, **kw):
    while True:
        try:
            p_req = pokemon_pb2.RequestEnvelop()
            p_req.rpc_id = 1469378659230941192

            p_req.unknown1 = 2

            p_req.latitude, p_req.longitude, p_req.altitude = get_location_coords()

            p_req.unknown12 = 989

            if 'useauth' not in kw or not kw['useauth']:
                p_req.auth.provider = 'ptc'
                p_req.auth.token.contents = access_token
                p_req.auth.token.unknown13 = 14
            else:
                p_req.unknown11.unknown71 = kw['useauth'].unknown71
                p_req.unknown11.unknown72 = kw['useauth'].unknown72
                p_req.unknown11.unknown73 = kw['useauth'].unknown73

            for meh in mehs:
                p_req.MergeFrom(meh)

            protobuf = p_req.SerializeToString()

            r = SESSION.post(api_endpoint, data=protobuf, verify=False)
            reqtime = time.time()

            p_ret = pokemon_pb2.ResponseEnvelop()
            p_ret.ParseFromString(r.content)

            if DEBUG:
                print("REQUEST:")
                print(p_req)
                print("Response:")
                print(p_ret)
                print("\n\n")

            if DEBUG:
                print("[ ] Sleeping for 1 second")
            time.sleep(1)
            return (reqtime, p_ret)
        except Exception as e:
            if DEBUG:
                print(e)
            print('[-] API request error, retrying')
            time.sleep(1)
            continue

def get_profile(access_token, api, useauth, *reqq):
    req = pokemon_pb2.RequestEnvelop()

    req1 = req.requests.add()
    req1.type = 2
    if len(reqq) >= 1:
        req1.MergeFrom(reqq[0])

    req2 = req.requests.add()
    req2.type = 126
    if len(reqq) >= 2:
        req2.MergeFrom(reqq[1])

    req3 = req.requests.add()
    req3.type = 4
    if len(reqq) >= 3:
        req3.MergeFrom(reqq[2])

    req4 = req.requests.add()
    req4.type = 129
    if len(reqq) >= 4:
        req4.MergeFrom(reqq[3])

    req5 = req.requests.add()
    req5.type = 5
    if len(reqq) >= 5:
        req5.MergeFrom(reqq[4])

    return api_req(api, access_token, req, useauth = useauth)

def get_api_endpoint(access_token, api = API_URL):
    (rtime, p_ret) = get_profile(access_token, api, None)
    try:
        if p_ret.api_url:
            return ('https://%s/rpc' % p_ret.api_url)
        else:
            return None
    except:
        return None


def login_ptc(username, password):
    print('[!] login for: {}'.format(username))
    head = {'User-Agent': 'niantic'}
    r = SESSION.get(LOGIN_URL, headers=head)
    jdata = json.loads(r.content)
    data = {
        'lt': jdata['lt'],
        'execution': jdata['execution'],
        '_eventId': 'submit',
        'username': username,
        'password': password,
    }
    r1 = SESSION.post(LOGIN_URL, data=data, headers=head)

    ticket = None
    try:
        ticket = re.sub('.*ticket=', '', r1.history[0].headers['Location'])
    except Exception as e:
        if DEBUG:
            print(r1.json()['errors'][0])
        return None

    data1 = {
        'client_id': 'mobile-app_pokemon-go',
        'redirect_uri': 'https://www.nianticlabs.com/pokemongo/error',
        'client_secret': 'w8ScCUXJQc6kXKw8FiOhd8Fixzht18Dq3PEVkUCP5ZPxtgyWsbTvWHFLm2wNY0JR',
        'grant_type': 'refresh_token',
        'code': ticket,
    }
    r2 = SESSION.post(LOGIN_OAUTH, data=data1)
    access_token = re.sub('&expires.*', '', r2.content)
    access_token = re.sub('.*access_token=', '', access_token)
    return access_token

def raw_heartbeat(api_endpoint, access_token, response):
    m4 = pokemon_pb2.RequestEnvelop.Requests()
    m = pokemon_pb2.RequestEnvelop.MessageSingleInt()
    m.f1 = int(time.time() * 1000)
    m4.message = m.SerializeToString()
    m5 = pokemon_pb2.RequestEnvelop.Requests()
    m = pokemon_pb2.RequestEnvelop.MessageSingleString()
    m.bytes = "05daf51635c82611d1aac95c0b051d3ec088a930"
    m5.message = m.SerializeToString()

    walk = sorted(getNeighbors())

    m1 = pokemon_pb2.RequestEnvelop.Requests()
    m1.type = 106
    m = pokemon_pb2.RequestEnvelop.MessageQuad()
    m.f1 = ''.join(map(encode, walk))
    m.f2 = "\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000"
    m.lat = COORDS_LATITUDE
    m.long = COORDS_LONGITUDE
    m1.message = m.SerializeToString()
    while True:
        (hbtime, response) = get_profile(
            access_token,
            api_endpoint,
            response.unknown7,
            m1,
            pokemon_pb2.RequestEnvelop.Requests(),
            m4,
            pokemon_pb2.RequestEnvelop.Requests(),
            m5)
        if response.payload:
            break
    payload = response.payload[0]
    heartbeat = pokemon_pb2.ResponseEnvelop.HeartbeatPayload()
    heartbeat.ParseFromString(payload)
    return ((FLOAT_LAT, FLOAT_LONG), hbtime, heartbeat)

def heartbeat(api_endpoint, access_token, response):
    while True:
        try:
            h = raw_heartbeat(api_endpoint, access_token, response)
            return h
        except Exception, e:
            if DEBUG:
                print(e)
            print('[-] Heartbeat missed, retrying')


def scan(api_endpoint, access_token, response, origin, pokemons):
    steps = 0
    steplimit = NUM_STEPS
    pos = 1
    x   = 0
    y   = 0
    dx  = 0
    dy  = -1
    while steps < steplimit**2:
        original_lat = FLOAT_LAT
        original_long = FLOAT_LONG
        parent = CellId.from_lat_lng(LatLng.from_degrees(FLOAT_LAT, FLOAT_LONG)).parent(15)

        h = heartbeat(api_endpoint, access_token, response)
        hs = [h]
        seen = set([])
        for child in parent.children():
            latlng = LatLng.from_point(Cell(child).get_center())
            set_location_coords(latlng.lat().degrees, latlng.lng().degrees, 0)
            hs.append(heartbeat(api_endpoint, access_token, response))
        set_location_coords(original_lat, original_long, 0)

        visible = []

        for (coords, hbtime, hh) in hs:
            add_pokemon(-1, 'player', coords[0], coords[1], hbtime, 5)
            for cell in hh.cells:
                for wild in cell.WildPokemon:
                    hash = wild.SpawnPointId + ':' + str(wild.pokemon.PokemonId)
                    if (hash not in seen):
                        visible.append((hbtime, wild))
                        seen.add(hash)

        for cell in h[2].cells:
            if cell.NearbyPokemon:
                other = LatLng.from_point(Cell(CellId(cell.S2CellId)).get_center())
                diff = other - origin
                # print(diff)
                difflat = diff.lat().degrees
                difflng = diff.lng().degrees
                if len(cell.NearbyPokemon) > 0:
                    print('[+] Found pokemon!')
                for poke in cell.NearbyPokemon:
                        print('    (%s) %s' % (poke.PokedexNumber, pokemons[poke.PokedexNumber - 1]['Name']))

        for (timestamp, poke) in visible:
            other = LatLng.from_degrees(poke.Latitude, poke.Longitude)
            diff = other - origin
            # print(diff)
            difflat = diff.lat().degrees
            difflng = diff.lng().degrees

            add_pokemon(poke.pokemon.PokemonId, pokemons[poke.pokemon.PokemonId - 1]['Name'], poke.Latitude, poke.Longitude, timestamp, poke.TimeTillHiddenMs / 1000)

        write_data_to_file()
        if (-steplimit/2 < x <= steplimit/2) and (-steplimit/2 < y <= steplimit/2):
            set_location_coords((x * 0.0025) + deflat, (y * 0.0025 ) + deflng, 0)
        if x == y or (x < 0 and x == -y) or (x > 0 and x == 1-y):
            dx, dy = -dy, dx
        x, y = x+dx, y+dy
        steps +=1

        print('[+] Scan: %0.1f %%' % (((steps + (pos * .25) - .25) / steplimit**2) * 100))

def main():
    pokemons = json.load(open('pokemon.json'))
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", help="PTC Username", required=True)
    parser.add_argument("-p", "--password", help="PTC Password", required=True)
    parser.add_argument("-l", "--location", help="Location", required=True)
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true')
    parser.set_defaults(DEBUG=False)
    args = parser.parse_args()

    if args.debug:
        global DEBUG
        DEBUG = True
        print('[!] DEBUG mode on')

    set_location(args.location)

    access_token = login_ptc(args.username, args.password)
    if access_token is None:
        print('[-] Error logging in: possible wrong username/password')
        return
    print('[+] RPC Session Token: {} ...'.format(access_token[:25]))

    while True:
        api_endpoint = get_api_endpoint(access_token)
        if api_endpoint is None:
            print('[-] RPC server offline')
        else:
            break
    print('[+] Received API endpoint: {}'.format(api_endpoint))

    while True:
        (rtime, response) = get_profile(access_token, api_endpoint, None)
        if response is not None and len(response.payload):
            print('[+] Login successful')

            payload = response.payload[0]
            profile = pokemon_pb2.ResponseEnvelop.ProfilePayload()
            profile.ParseFromString(payload)
            print('[+] Username: {}'.format(profile.profile.username))

            creation_time = datetime.fromtimestamp(int(profile.profile.creation_time)/1000)
            print('[+] You are playing Pokemon Go since: {}'.format(
                creation_time.strftime('%Y-%m-%d %H:%M:%S'),
            ))

            for curr in profile.profile.currency:
                print('[+] {}: {}'.format(curr.type, curr.amount))

            break
        else:
            print('[-] Ooops...')

    origin = LatLng.from_degrees(FLOAT_LAT, FLOAT_LONG)

    while True:
        scan(api_endpoint, access_token, response, origin, pokemons)


if __name__ == '__main__':
    main()
