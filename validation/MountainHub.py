from datetime import datetime
import time

import pandas as pd
import requests
import config

BASE_URL = 'https://api.mountainhub.com/timeline'
BASE_ELEVATION_URL = 'https://maps.googleapis.com/maps/api/elevation/json'
HEADER = { 'Accept-version': '1' }

def batches(list, size):
    """Splits list into batches of fixed size.

    Keword arguments:
    list -- List to split
    size -- Batch size
    """
    for i in range(0, len(list), size):
        yield list[i:i + size]

def intervals(start, end, intervals):
    """Generates series of evenly spaced intervals between two numbers.

    Keyword arguments:
    start -- Lower bound
    end -- Upper bound
    intervals -- Number of points to generate
    """
    stop = 0
    while stop < stops:
        yield (start + stop * (end - start) / (stops - 1))
        stop += 1

def removeEmptyParams(dict):
    """Returns copy of dictionary with empty values removed.

    Keyword arguments:
    dict -- Dictionary to process
    """
    return { k:v for k, v in dict.items() if v is not None }

def dateToTimestamp(date):
    """Converts datetime object to unix timestamp.

    Keyword arguments:
    date -- Datetime object to convert
    """
    if date is None:
        return date
    return int(time.mktime(date.timetuple())) * 1000

def timestampToDate(timestamp):
    """Converts unix timestamp to datettime object.

    Keyword arguments:
    timestamp -- Timestamp to convert
    """
    if timestamp is None:
        return timestamp
    return datetime.fromtimestamp(timestamp / 1000)

def make_box(box):
    """Formats bounding box for use in MountainHub API.

    Keyword arguments:
    box -- Dictionary used to construct box
    """
    if box is None:
        return {}
    return {
        'north_east_lat': box['ymax'],
        'north_east_lng': box['xmax'],
        'south_west_lat': box['ymin'],
        'south_west_lng': box['xmin']
    }

def parse_snow(record):
    """Parses record returned by MountainHub API into standard format.

    Keyword arguments:
    record -- Segment of JSON returned by MountainHub API
    """
    obs = record['observation']
    actor = record['actor']
    details = obs.get('details', [{}])
    snow_depth = details[0].get('snowpack_depth') if len(details) > 0 and details[0] is not None else None
    # Remap record structure
    return {
        'author_name' : actor.get('full_name') or actor.get('fullName'),
        'id' : obs['_id'],
        'timestamp' : int(obs['reported_at']),
        'date' : timestampToDate(int(obs['reported_at'])),
        'lat' : obs['location'][1],
        'long' : obs['location'][0],
        'type' : obs['type'],
        'snow_depth' : float(snow_depth) if (snow_depth is not None and snow_depth != 'undefined')else None
    }

def parse_elevation(record):
    """Parses record returned by Google Elevation API into standard format.

    Keyword arguments:
    record -- Segment of JSON returned by Google Elevation API
    """
    return {
        'elevation' : record['elevation']
    }

def snow_data(limit=100, start=None, end=None, box=None, filter=True):
    """Retrieves snow data from MountainHub API.

    Keyword arguments:
    limit -- Maximum number of records to return (default 100)
    start -- Start date to return results from
    end -- End date to return results from
    box -- Bounding box to restrict results,
    filter -- Flag indicating whether entries with no snow depth data should be filtered out
    """
    # Build API request
    params = removeEmptyParams({
        'publisher': 'all',
        'obs_type': 'snow_conditions',
        'limit': limit,
        'since': dateToTimestamp(start),
        'before': dateToTimestamp(end),
        **make_box(box)
    })

    # Make request
    response = requests.get(BASE_URL, params=params, headers=HEADER)
    data = response.json()

    if 'results' not in data:
        raise ValueError(data)

    # Parse request
    records = data['results']
    parsed = [ parse_snow(record) for record in records ]

    # Convert to dataframe and drop invalid results if necessary
    df = pd.DataFrame.from_records(parsed)
    if filter:
        df = df.dropna()
    return df

def el_data(points=[]):
    """Retrieves elevation data from Google Elevation API.

    Keyword arguments:
    points -- List of coordinates to retrieve elevation data at
    """
    records = []
    # Split into batches for API requests
    for batch in batches(points, 256):
        params = {
            'locations': "|".join([",".join([str(point[0]), str(point[1])]) for point in points]),
            'key': config.GOOGLE_API_KEY
        }
        response = requests.get(BASE_ELEVATION_URL, params=params)
        data = response.json()

        if 'results' not in data:
            raise ValueError(data)

        records.extend(data['results'])
    parsed = [{ 'lat' : point[0], 'long' : point[1], **parse_elevation(record)} for point, record in zip(points, records)]
    df = pd.DataFrame.from_records(parsed)
    return df

def average_elevation(box, grid_size = 16):
    """Approximates elevation over a bounding box using a grid of points.

    Keyword arguments:
    box -- Dictionary representing box to retrieve elevation data over
    grid_size -- Number of intervals used in each direction to approximate elevation
    """
    # Restrict grid size to fit in API request
    grid_size = min(grid_size, 16)
    points = []
    for lat in intervals(box['ymin'], box['ymax'], grid_size):
        for long in intervals(box['xmin'], box['xmax'], grid_size):
            points.append((lat, long))

    params = {
        'locations': "|".join([",".join(['%.4f' % point[0], '%.4f' % point[1]]) for point in points]),
        'key': config.GOOGLE_API_KEY
    }
    print(params)
    response = requests.get(BASE_ELEVATION_URL, params=params)
    print(response.text)
    data = response.json()

    if 'results' not in data:
        raise ValueError(data)

    records = data['results']
    elevations = [record['elevation'] for record in records]
    print(sum(elevations) / len(elevations))
    return sum(elevations) / len(elevations)


def merge_el_data(df):
    """Merges elevation data with snow depth observations data.

    Keyword arguments:
    df -- Dataframe of SNODAS data to add elevation data to
    """
    points = list(zip(df['lat'], df['long']))
    elevations = el_data(points)
    return pd.merge(df, elevations)