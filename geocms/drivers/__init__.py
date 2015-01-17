import cPickle
from hashlib import md5
from datetime import datetime
from urllib2 import urlopen
from django.utils.timezone import utc
from django.core.files import File
import os
from django.conf import settings as s
import sh
import requests
from tempfile import NamedTemporaryFile
import logging
import importlib

from terrapyn.geocms import cache, predicates


try:
   import mapnik
except ImportError:
   import mapnik2 as mapnik

from osgeo import osr

VECTOR = False
RASTER = True

_log = logging.getLogger('terrapyn.driver_messages')

def get_driver(name):
    driver_module = importlib.import_module(name)
    for toplevel in (getattr(driver_module, t) for t in dir(driver_module)):
        if issubclass(toplevel, Driver) and toplevel is not Driver:
            return toplevel

class Driver(object):
    """Abstract class that defines a number of reusable methods to load geographic data and create services from it"""

    def __init__(self, data_resource, **kwargs):
        _log.debug('created driver for {0}'.format(data_resource.slug))
        self.resource = data_resource
        self.cache_path = cache.data_cache_path(data_resource)
        self.cached_basename = os.path.join(self.cache_path, os.path.split(self.resource.slug)[-1])
        self.src_ext = '.sqlite'  # default
        self.ready_data_resource(**kwargs)

    @property
    def objects(self):
        raise NotImplementedError()

    def get_resource_extension(self):
        return 'sqlite'

    def cache_data_file(self, freshen=False):
        """
        Ensures that if a resource comes from a URL that it has been retrieved in its entirety.

        :param freshen: True if this file should be downloaded and the cache obliterated.  False otherwise.

        :return: True if the file has changed since the last time this was called.  False if the file has not changed
                and None if there is no local file to be had (true for PostGIS driver and some custom drivers)
        """

        # immediately return if local caching isn't supported
        if self.resource.resource_file and not freshen:
            _log.debug('using cached file at {0} for {1}'.format(self.resource.resource_file.name, self.resource.slug))
            # if we've cached this file before, it's saved in the resource object.  Ensure that it's on local storage.
            self._ensure_local()
            return False
        else:  # clear the cache and recreate it if we specified "freshen" or if a cached file doesn't exist
            _log.info('processing file to add to cache for {0}'.format(self.resource.slug))
            cache.delete_data_cache(self.resource)
            cache.data_cache_path(self.resource)

            if self.resource.resource_url:
                tempfile = self._fetch_data()
                processed_file, log = self.process_data(tempfile)
            else:
                processed_file, log = self.process_data(self.resource.original_file)

            self.resource.resource_file = processed_file
            self.resource.resource_file.save(self.resource.slug + '.' + self.get_resource_extension(), processed_file)
            self.resource.import_log = log
            self.resource.save()
            self._ensure_local()
            return True


    def _fetch_data(self):

        # get the original source extensions, since GDAL/OGR uses it to determine file type for the source file
        _log.info('fetching data for {0}'.format(self.resource.slug))

        _, ext = os.path.splitext(self.resource.resource_url)
        tmp = NamedTemporaryFile(suffix='.' + ext)

        # requests doesn't handle FTP natively, so use urllib
        if self.resource.resource_url.startswith('ftp'):
            result = urlopen(self.resource.resource_url).read()
            if result:
                tmp.write(result)
            else:
                _log.error('cannot fetch data for {0} because of error opening {1}'.format(self.resource.slug, self.resource.resource_url))
        else:
            result = requests.get(self.resource.resource_url)
            if result.ok:
                tmp.write(result.content)
            else:
                _log.error('cannot fetch data for {0} because of an error opening {1}'.format(self.resource.slug, self.resource.resource_url))
                _log.error(result.content)

        tmp.flush()
        tmp.seek(0)
        return tmp

    def process_data(self, data_file):
        """Implement this method in subclasses. If you call it in the super class, do so last."""
        if isinstance(data_file, File):
            return data_file
        else:
            return File(data_file)

    def _ensure_local(self):
        _log.debug('ensuring file is on local disk. some storages may use remote files.')
        cached_filename = self.get_filename()
        if os.path.exists(cached_filename):
            return
        elif os.path.exists(os.path.join(s.MEDIA_ROOT, self.resource.resource_file.name)):
            _log.info('{0} file exists on filesystem, but not in cache directory. copying using OS.'.format(self.resource.slug))
            sh.cp(os.path.join(s.MEDIA_ROOT, self.resource.resource_file.name), cached_filename)
        else:
            _log.info('{0} file exists on remote storage. copying by hand.'.format(self.resource.slug))
            with open(cached_filename, 'wb') as out:
                for chunk in self.resource.resource_file.chunks():
                    out.write(chunk)

    def data_size(self):
        sz = self.resource.resource_file.size if self.resource.resource_file else 0
        for line in sh.du('-cs', self.cache_path):
            if line.startswith('.'):
                sz += int(line.split(' ')[-1])
        return sz


    @classmethod
    def supports_multiple_layers(cls):
        """If a single resource can contain multiple layers, this returns True."""

        return True

    @classmethod
    def supports_download(cls):
        """If a user could download the resource in its entirety, this returns True."""

        return True

    @classmethod
    def supports_related(cls):
        """True if this driver supports "join-on-key" functionality with the RelatedResource model"""
        return True

    @classmethod
    def supports_upload(cls):
        """True if the user can upload a file as part of this reosurce"""
        return True

    @classmethod
    def supports_configuration(cls):
        """True if the resource must be configured with a resource_config attribute"""
        return True

    @classmethod
    def supports_point_query(cls):
        """True if a single geographic point can be queried."""
        return True

    @classmethod
    def supports_spatial_query(cls):
        """True if a spatial query or bounding box can be queried"""
        return True

    @classmethod
    def supports_rest(cls):
        """True if the REST API is supported for data sources"""
        return True

    @classmethod
    def supports_local_caching(cls):
        """True if the whole resource is downloaded and cached locally.  False for stream-based drivers"""
        return True

    @classmethod
    def datatype(cls):
        """returns VECTOR or RASTER"""
        return VECTOR

    def filestream(self):
        """returns an open file stream from the locally cached file.  Must support local caching."""

        self.cache_data_file()
        return open(self.cached_basename + self.src_ext)

    def mimetype(self):
        """The mime type to use when returning the original resource file via HTTP"""
        return "application/octet-stream"

    def ready_data_resource(self, **kwargs):
        """Abstract. Ensures that the file is local and ensures that spatial metadata has been computed for the resource.
        Full implementations of this method should also return a mapnik config dictionary as the last item of the tuple.

        :return: a tuple that includes the resource slug and the spatial reference system as a osr.SpatialReference object
        """

        changed = self.cache_data_file(freshen='fresh' in kwargs and kwargs['fresh'])
        if changed:
            _log.info('underlying resource file has changed for {0}. computing spatial metadata'.format(self.resource.slug))
            self.compute_spatial_metadata()

    def get_rendering_parameters(self, **kwargs):
        raise NotImplementedError()

    def compute_spatial_metadata(self):
        """
        Compute the spatial metadata fields in the DataResource. Abstract.
        """
        _log.info('saving md5sum for cached file.')
        md5sum = self._compute_md5sum()
        if md5sum != self.resource.md5sum:
            self.resource.md5sum = md5sum
            self.resource.last_change = datetime.utcnow().replace(tzinfo=utc)
            self.resource.save()

    def _compute_md5sum(self):
        filehash = md5()
        with open(self.get_filename()) as f:
            b = f.read(10 * 1024768)
            while b:
                filehash.update(b)
                b = f.read(10 * 1024768)

        return filehash.hexdigest()


    def get_metadata(self, **kwargs):
        """Abstract. If there is metadata conforming to some standard, then return it here"""
        return {}

    def get_data_fields(self, **kwargs):
        """If this is a shapefile, return the names of the fields in the DBF and their datattypes.  If this is a data
        raster (as opposed to an RGB or grayscale raster, return the names of the bands or subdatasets and their
        datatypes."""
        return []

    def get_filename(self, xtn=None):
        """
        Get a filename for a cached entity related to the underlying resource.

        :param xtn: The file extension to used.
        :return: The cached filename.  No guarantees it exists. The filename consists of the original filename stripped
        of its extension and the new extension appended.
        """
        xtn = xtn or self.get_resource_extension()

        if not xtn.startswith('.'):
            xtn = '.' + xtn

        return self.cached_basename + xtn

    def get_data_for_point(self, wherex, wherey, srs, fuzziness=30, **kwargs):
        """
        Get data for a single x,y point.  This should be supported for raw rasters as well as vector data, but obviously
        RGB data is kind of pointless.

        :param wherex: the x coordinate
        :param wherey: the y coordinate
        :param srs: a spatial reference system, either as a string EPSG:#### or PROJ.4 string, or as an osr.SpatialReference
        :param fuzziness: the distance in map units from the xy coodrinate that features data should be pulled from
        :param kwargs: if fuzziness is 0, then keyword args bbox, width, and height should be passed in to let the
            engine figure out how big a "point" is.
        :return: a four-tuple of:
        """
        _, nativesrs, result = self.get_rendering_parameters(**kwargs)

        s_srs = osr.SpatialReference()
        t_srs = nativesrs

        if isinstance(srs, osr.SpatialReference):
            s_srs = srs
        elif srs.lower().startswith('epsg'):
            s_srs.ImportFromEPSG(int(srs.split(':')[-1]))
        else:
            s_srs.ImportFromProj4(srs.encode('ascii'))

        crx = osr.CoordinateTransformation(s_srs, t_srs)
        x1, y1, _ = crx.TransformPoint(wherex, wherey)
        
        # transform wherex and wherey to 3857 and then add $fuzziness meters to them
        # transform the fuzzy coords to $nativesrs
        # substract fuzzy coords from x1 and y1 to get the fuzziness needed in the native coordinate space
        epsilon = 0
        if fuzziness > 0:
           meters = osr.SpatialReference()
           meters.ImportFromEPSG(3857) # use web mercator for meters
           nat2met = osr.CoordinateTransformation(s_srs, meters) # switch from the input srs to the metric one
           met2nat = osr.CoordinateTransformation(meters, t_srs) # switch from the metric srs to the native one
           mx, my, _ = nat2met.TransformPoint(wherex, wherey) # calculate the input coordinates in meters
           fx = mx+fuzziness # add metric fuzziness to the x coordinate only to get a radius
           fy = my 
           fx, fy, _ = met2nat.TransformPoint(fx, fy)
           epsilon = fx - x1 # the geometry should be buffered by this much
        elif 'bbox' in kwargs and 'width' in kwargs and 'height' in kwargs:
           # use the bounding box to calculate a radius of 8 pixels around the input point
           minx, miny, maxx, maxy = kwargs['bbox']
           width = int(kwargs['width']) # the tile width in pixels
           height = int(kwargs['height']) # the tile height in pixels
           dy = (maxy-miny)/height # the height delta in native coordinate units between pixels
           dx = (maxx-minx)/width # the width delta in native coordinate units between pixels
           x2, y2, _ = crx.TransformPoint(wherex+dx*8, wherey) # return a point 8 pixels to the right of the source point in native coordinate units
           epsilon = x2 - x1 # the geometry should be buffered by this much
        else:
           pass

        return result, x1, y1, epsilon

    def as_dataframe(self, **kwargs):
        """Return the entire dataset as a pandas dataframe"""

        raise NotImplementedError("This driver does not support dataframes")

    def summary(self, **kwargs):
        """Requires dataframe support.  Return a summary of the dataframe using pandas's standard methods and our own
        predicates"""

        try:
            sum_path = self.get_filename('sum')
            if self.resource.big and os.path.exists(sum_path):
                with open(sum_path) as sm:
                    return cPickle.load(sm)

            df = self.as_dataframe(**kwargs)
        except NotImplementedError:
            return None

        keys = [k for k in df.keys() if k != 'geometry']
        type_table = {
            'float64': 'number',
            'int64': 'number',
            'object': 'text'
        }

        ctx = [{'name': k} for k in keys]
        for i, k in enumerate(keys):
            s = df[k]
            ctx[i]['kind'] = type_table[s.dtype.name]
            ctx[i]['tags'] = [tag for tag in [
                'unique' if predicates.unique(s) else None,
                'not null' if predicates.not_null(s) else None,
                'null' if predicates.some_null(s) else None,
                'empty' if predicates.all_null(s) else None,
                'categorical' if predicates.categorical(s) else None,
                'open ended' if predicates.continuous(s) else None,
                'mostly null' if predicates.mostly_null(s) else None,
                'uniform' if predicates.uniform(s) else None
            ] if tag]
            if 'categorical' in ctx[i]['tags']:
                ctx[i]['uniques'] = [x for x in s.unique()]
            for k, v in s.describe().to_dict().items():
                ctx[i][k] = v

        if self.resource.big:
            with open(sum_path, 'w') as sm:
                cPickle.dump(ctx, sm)

        return ctx


