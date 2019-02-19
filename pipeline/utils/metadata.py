#!/usr/bin/env python

import logging


from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from astropy.constants import R_earth
from calcos import orbit
from calcos.timeline import gmst, DEGtoRAD, rectToSph
import numpy as np
import os



logging.basicConfig(format='%(levelname)-4s '
                           '[%(module)s.%(funcName)s:%(lineno)d]'
                           ' %(message)s',
                    level=logging.DEBUG)

LOG = logging.getLogger('CosmicRayPipeline')

LOG.setLevel(logging.INFO)

class GenerateMetadata(object):
    """
    Class for generating and storing relevant metadata for each file

    Parameters
    ----------
    fname : str
        Name of FITS file

    instr_cfg : dict
        Instrument specific configuration object

    """
    def __init__(self, fname, instr_cfg=None):
        self._fname = fname # file name will always be the FLT
        self._instr_cfg = instr_cfg
        self._telemetry_file = None
        self._date = None
        self._metadata = {}



    @property
    def fname(self):
        """Name of FITS file"""
        return self._fname

    @property
    def instr_cfg(self):
        """Instrument specific configuration object"""
        return self._instr_cfg

    @property
    def telemetry_file(self):
        """Full path to corresponding telemetry file for :py:attr:`fname`"""
        return self._telemetry_file

    @telemetry_file.setter
    def telemetry_file(self, value):
        self._telemetry_file = value

    @property
    def metadata(self):
        """Dictionary used to store relevant metadata"""
        return self._metadata

    @metadata.setter
    def metadata(self, value):
        self._metadata = value


    def _engineering_file(self):
        """ Generate path to telemetry file

        Returns
        -------

        """
        telemetry_suffix = \
            self.instr_cfg['astroquery']['SubGroupDescription'][1].lower()

        self.telemetry_file = self.fname.replace('flt', telemetry_suffix)


    def get_wcs_info(self):
        """ Parse the WCS information to determine the telescope pointing

        This method will record all of the WCS information stored in the
        header.

        Return
        -------

        """
        with fits.open(self.fname) as hdu:
            try:
                wcs_obj = WCS(fobj = hdu, header = hdu[1].header)
            except (MemoryError, ValueError, KeyError) as e:
                LOG.error(e)
            else:
                wcs_header = wcs_obj.to_header()
                for key in wcs_header.keys():
                    self.metadata[key] = wcs_header[key]

    def get_image_data(self):
        """Parse the FITS header and retrieve important keywords

        This will store the following keywords:

            - `date-obs`
            - `expstart`
            - `expend`
            - `exptime`
            - `flashdur` (if it exists)
            - `time-obs`

        `date-obs` and `time-obs` are combined into a single string in ISO
        format (YYYY-MM-DD HH:MM:SS).

        `exptime` and `flashdur` are combined with the `readout_time` of the
        detector to compute the total integration time.


        Returns
        -------

        """
        header_data = {'date-obs': None,
                       'expstart': None,
                       'expend': None,
                       'exptime': None,
                       'flashdur': 0,
                       'time-obs': None}

        with fits.open(self.fname) as hdu:
            prhdr = hdu[0].header
            scihdr = hdu[1].header
            for key in header_data.keys():
                try:
                    header_data[key] = prhdr[key]
                except KeyError as e:
                    # LOG.warning('{}\n Searching SCI header\n'.format(e))
                    try:
                        header_data[key] = scihdr[key]
                    except KeyError as e:
                        LOG.warning('{}'.format(e))


        date = Time(
            '{} {}'.format(header_data['date-obs'], header_data['time-obs']),
            format='iso'
        )

        self.metadata['date'] = date.iso
        self.metadata['expstart'] = Time(header_data['expstart'], format='mjd')
        self.metadata['expend'] = Time(header_data['expend'], format='mjd')
        self.metadata['integration_time'] = \
            header_data['exptime'] + \
            header_data['flashdur'] + \
            self.instr_cfg['instr_params']['readout_time']


    def get_observatory_info(self):
        """Compute the lat/lon and altitude of HST.

        Using the expstart and expend, generate a series MJD dates that correspond
        to 1 minute intervals. Calculate the lat/lon and altitude at each
        time step.

        """

        altitude_list = []
        lat_list = []
        lon_list = []

        # Break up the exposure into one minute intervals
        time_delta = self.metadata['expend'] - self.metadata['expstart']
        num_intervals = int(time_delta.to('minute').value)

        # If the number of one minute intervals is less than 2, set the number
        # of intervals to 5 (arbitrarily chosen)
        if num_intervals < 2:
            num_intervals = 5
        # Generate MJD dates correspond to these one minute intervals
        time_intervals = np.linspace(self.metadata['expstart'].mjd,
                                     self.metadata['expend'].mjd,
                                     num_intervals,
                                     endpoint=True)

        # Generate the path to the engineering file
        self._engineering_file()
        # Using the telemetry data for the SPT file, compute HST (lon, lat, z)
        if os.path.isfile(self.telemetry_file):
            orbital_params = orbit.HSTOrbit(self.telemetry_file)
            # compute coords at beginning and end of exposure
            for t in time_intervals:
                rect, vel = orbital_params.getPos(t)
                r, ra, dec = rectToSph(rect)
                altitude_list.append(r - R_earth.to('km').value)
                lat = dec
                lon = ra - 2 * np.pi * gmst(t)
                if lon < 0:
                    lon += 2 * np.pi
                lon /= DEGtoRAD
                lat /= DEGtoRAD
                lat_list.append(lat)
                lon_list.append(lon)

            self.metadata['latitude'] = np.asarray(lat_list)
            self.metadata['longitude'] = np.asarray(lon_list)
            self.metadata['altitude'] = np.asarray(altitude_list)
            self.metadata['time_intervals'] = time_intervals
        else:
            # If the SPT file for some reason doesn't exist, save NaNs
            self.metadata['altitude'] = np.nan
            self.metadata['latitude'] = np.nan
            self.metadata['longitude'] = np.nan
            self.metadata['time_intervals'] = np.nan









