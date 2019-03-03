#!/usr/bin/env python
"""
This module contains all the functionality required to perform a
connected-component labeling analysis. It is broken into two classes, one base
class for arbtirary label objects and one specific to cosmic rays
"""
from collections import Iterable
import logging

from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.visualization import ImageNormalize, LinearStretch, ZScaleInterval

import matplotlib.pyplot as plt
from matplotlib import colors
import numpy as np
from scipy import ndimage


logging.basicConfig(format='%(levelname)-4s '
                           '[%(module)s.%(funcName)s:%(lineno)d]'
                           ' %(message)s')

LOG = logging.getLogger()

LOG.setLevel(logging.INFO)

class Label(object):
    """Base class for cosmic ray labelers to be used in both IR and CCD analyses

    Parameters
    ----------
    fname : str
        Name of FITS file

    """
    def __init__(self, fname, gain_keyword=None):


        self._fname = fname
        self._gain_keyword = gain_keyword
        self._label = None
        self._dq = None
        self._sci = None
        self._exptime = 0

    @property
    def fname(self):
        """Name of FITS file"""
        return self._fname

    @property
    def gain_keyword(self):
        return self._gain_keyword

    @gain_keyword.getter
    def gain_keyword(self):
        """Header keyword for obtaining CCD gain information"""
        return self._gain_keyword

    @gain_keyword.setter
    def gain_keyword(self, value):
        self._gain_keyword = value

    @property
    def label(self):
        """Generated label"""
        return self._label

    @label.setter
    def label(self, value):
        self._label = value

    @property
    def dq(self):
        """A concatenated version of all DQ extensions in :py:attr:`fname`"""
        return self._dq

    @dq.setter
    def dq(self, value):
        self._dq = value

    @property
    def exptime(self):
        """Total integration time of the observation"""
        return self._exptime

    @exptime.setter
    def exptime(self, value):
        self._exptime = value

    @property
    def sci(self):
        """A concatenated version of all SCI extensions in :py:attr:`fname`"""
        return self._sci


    @sci.setter
    def sci(self, value):
        self._sci = value

    def get_data(self, extname='dq', extnums=[1,2]):
        """ Grab the data from extensions named EXT from FITS file

        Parameters
        ----------
        extname : str
            Name of extension to extract data from (e.g. 'SCI' or 'DQ')

        extnums : list
            List of the extension numbers. This should always be a list, even
            if it just contains one element
        """
        ext_tuples = [(extname, num) for num in extnums]
        ext_data = []
        with fits.open(self.fname) as hdu:
            units = hdu[1].header['BUNIT']
            if self.gain_keyword is not None:
                # For CCD's with multiple readout amplifiers the line below
                # returns an astropy.header.Header object with all the matching
                # keywords. Hence, we must compute the average CCD gain if
                # there are multiple readout amplifiers
                gain_values = hdu[0].header[self.gain_keyword]
                if isinstance(gain_values, Iterable):
                    filtered_gains = list(
                        filter(lambda g: g != 0, gain_values.values())
                    )
                    # Compute the average of all nonzero gains
                    avg_gain = sum(filtered_gains)/ len(filtered_gains)
                else:
                    avg_gain = gain_values

            for val in ext_tuples:
                try:
                    ext = hdu.index_of(val)
                except KeyError:
                    LOG.warning('{} is missing for {}'.format(val, self.fname))
                else:
                    ext_data.append(hdu[ext].data)

            # Get the EXPTIME of the observation.
            # For STIS, this is always stored in the SCI extension header.
            try:
                exptime =  hdu[0].header['EXPTIME']
            except KeyError as e:
                LOG.warning('{}\n Searching SCI header'.format(e))
                exptime =  hdu[1].header['EXPTIME']
            finally:
                self.exptime = exptime

            # Check for FLASHDUR keyword. Only ACS and WFC3 will have this
            # and it is always present in the Primary Header of the FITS file.
            try:
                flashdur = hdu[0].header['flashdur']
            except KeyError as e:
                LOG.warning('{}\n '.format(e))
            else:
                self.exptime += flashdur

        if extname == 'sci' and ext_data:
            if units == 'COUNTS' and self.gain_keyword is not None:
                msg = (
                    'Converting image from {}(DN) to ELECTRONS \n'
                    'Average gain computed from header: {}'.format(units,
                                                                   avg_gain)
                )
                LOG.info(msg)
                # If the data has units of DN, convert to electrons
                ext_data = [datum * avg_gain for datum in ext_data]
            self.sci = np.concatenate(ext_data, axis=0)

        elif extname == 'dq' and ext_data:
            self.dq = np.concatenate(ext_data, axis=0)


    def ccd_labeling(self, use_dq=True, dq_flag=8192, do_bitwise_comp=True,
                      deblend=False, threshold_l=2, threshold_u = 1000,
                      structure_element=np.ones((3, 3))):
        """ Run a label analysis on the DQ or SCI arrays of CCD dark frames

        If performed on the DQ arrays, there will be a bitwise comparison to
        find all pixels affected by cosmic rays and anything else. For example,
        if a hot pixel is hit by a cosmic ray, then it will have a DQ flag of
        8208 (8192 + 16). The bitwise comparison will ensure these pixels are
        included in the analysis.

        If performed on the SCI arrays, a binary image is generated by looking
        for all pixels that are strictly 5 :math:`\\sigma` above the
        sigma-clipped median of the image. The labeling analysis will then
        be performed this binary image.


        Parameters
        ----------
        use_dq : bool
            If True, label the DQ array. If false, label the science array

        dq_flag : int
            Flag to use for identifying objects in the DQ array

        do_bitwise_comp : bool
            If True, do a bitwise comparison prior to labeling analysiss

        debled : bool
            Deblend found sources to separate overlapping cosmic rays

        threshold_l : int
            Objects found that affect fewer pixels than this limit are removed

        threshold_u : int
            Objects found affect more pixels than this limit are removed

        structure_element : numpy.ndarray
            2-D array used to identified "connected" pixels. The default
            structure element used is the 8-connectivity matrix:

            .. math::
               \\begin{bmatrix} 1 & 1 &1 \\\ 1 & 1& 1 \\\ 1 & 1 & 1 \\end{bmatrix}

        Returns
        -------

        """
        if use_dq:
            array_to_label = self.dq
        else:
            # Generate some stats to use for the source detection
            mean, median, std = sigma_clipped_stats(self.sci,
                                                    sigma_lower=3,
                                                    sigma_upper=3)
            LOG.info('mean: {}, median: {}, std: {}'.format(mean, median, std))

            # Create an array of 1's and 0's using the SCI data
            array_to_label = np.where(self.sci > np.absolute(median) + 3 * std,
                                      1, 0)

        if do_bitwise_comp and use_dq:
            # Look for CR and remove bad pixels
            bad_pixels = np.bitwise_and(array_to_label, 4)
            crs = np.bitwise_and(array_to_label, dq_flag)
            array_to_label = np.where((crs > 0) &
                                      (bad_pixels == 0), dq_flag, 0)

        label, num_feat = ndimage.label(array_to_label,
                                        structure=structure_element)
        LOG.info('A total of {} objects were identified'.format(num_feat))

        cr_labels = label.ravel()  # Returns a flattened label
        # Count up the number of pixels associated with each unique label
        sizes = np.bincount(cr_labels)
        arg_max = np.argmax(sizes)
        sizes[arg_max] = 0
        large_CRs = (sizes > threshold_l) & (sizes < threshold_u)

        # Create a 2-D mask from the 1-D array of large cosmic rays, and set all
        # labels of cosmic rays smaller than threshold to 0 so they are ignored.
        label_mask = large_CRs[label]
        array_to_label[~label_mask] = 0
        label, num_feat = ndimage.label(array_to_label,
                                        structure=structure_element)

        LOG.info('After thresholding there are {} objects'.format(num_feat))
        self.label = label

        if deblend:
            LOG.info('Deblending...')

    # TODO: add functionality for deblending over-lapping cosmic rays
    def deblend_objects(self):
        """

        Returns
        -------

        """

    #TODO: Come up with a good scheme for labeling CRs in IR data
    def get_ir_label(self, samptime=None):
        """"""

    def mk_fig(self, show_axis_labels=True, show_grid=False):
        """Generate a figure with two axes for plotting the label

        Parameters
        ----------
        show_axis_labels : bool
            Show major tick labels on both axes

        show_grid : bool
            Show a grid

        Returns
        -------
        fig : matplotlib.figure.Figure
            Instance of a matplotlib Figure object

        ax1 : matplotlib.axes.Axes
            Instance of a maplotlib Axes object

        ax2 : matplotlib.axes.Axes
            Instance of a matplotlib Axes object


        """
        grid = plt.GridSpec(1, 2, wspace=0.2, hspace=0.15)
        fig = plt.figure(figsize=(8, 5))
        ax1 = fig.add_subplot(grid[0, 0])
        ax2 = fig.add_subplot(grid[0, 1], sharex=ax1, sharey=ax1)
        for ax in [ax1, ax2]:
            if show_grid:
                ax.grid(False)

            if not show_axis_labels:
                ax.tick_params(axis='both', bottom=False,
                               labelbottom=False,
                               left=False,
                               labelleft=False)
        return fig, ax1, ax2

    def plot(self, show=True, save=True):
        """ Plot the label

        Parameters
        ----------
        show : bool
            If True, show a plot of the data.

        Returns
        -------


        """

        fig, ax1, ax2 = self.mk_fig()
        ncolors = np.max(self.label) + 1
        prng = np.random.RandomState(1234)
        h = prng.uniform(low=0.0, high=1.0, size=ncolors)
        s = prng.uniform(low=0.2, high=0.7, size=ncolors)
        v = prng.uniform(low=0.5, high=1.0, size=ncolors)
        hsv = np.dstack((h, s, v))

        rgb = np.squeeze(colors.hsv_to_rgb(hsv))
        rgb[0] = (0,0,0)
        cmap = colors.ListedColormap(rgb)

        if self.sci is None:
            self.get_data(ext='sci')

        norm = ImageNormalize(self.sci,
                              stretch=LinearStretch(),
                              interval=ZScaleInterval())
        if isinstance(self.sci, list):
            ax1.imshow(self.sci[0], norm=norm, cmap='gray', origin='lower')
            ax2.imshow(self.label[0], cmap=cmap, origin='lower')
        else:
            ax1.imshow(self.sci, norm=norm, cmap='gray', origin='lower')
            ax2.imshow(self.label, cmap=cmap, origin='lower')

        ax1.set_xlim(850, 1000)
        ax1.set_ylim(100, 300)

        ax1.set_title('SCI Extension')
        ax2.set_title('Cosmic Ray Segmentation Map')
        if save:
            fig.savefig('example_plot.png', format='png', dpi=300)

        if show:
            plt.show()



class CosmicRayLabel(Label):
    """
    Class for generating the cosmic ray label

    Parameters
    ----------
    fname : str
        Name of FITS file

    instr : str
        Instrument currently being processed

    instr_cfg : dict
        Instrument specific configuration object


    """
    def __init__(self, fname, gain_keyword=None):
        super().__init__(fname, gain_keyword)


    def run_ccd_label(self, deblend=False, use_dq=True, extnums=[1,2],
                      threshold_l=None, threshold_u=None, plot=False):
        """ Run labeling algorithm on CCD data

        This will populate the following class attributes:

         - :py:attr:`~label.base.Label.dq`
         - :py:attr:`~label.base.Label.integration_time`
         - :py:attr:`~label.base.Label.label`
         - :py:attr:`~label.base.Label.sci`

        Parameters
        ----------
        deblend : bool
            If True, deblend overlapping cosmic rays

        extnums : list
            List of the extension numbers. This should always be a list, even
            if it just contains one element

        use_dq : bool
            If True, generate the label using the DQ information

        threshold_l : int
            Objects found that affect fewer pixels than this limit are removed

        threshold_u : int
            Objects found affect more pixels than this limit are removed


        Returns
        -------

        """
        # Get the DQ array only if we use it for label
        if use_dq:
            self.get_data(extname='dq', extnums=extnums)

        # Always get the SCI array
        self.get_data(extname='sci', extnums=extnums)

        self.ccd_labeling(use_dq = use_dq,
                          threshold_l=threshold_l,
                          deblend=deblend,
                          threshold_u=threshold_u)

        if plot:
            self.plot(show=True)






    def run_ir_label(self):
        """ Run labeling algorithm on IR data

        Returns
        -------

        """




def main():
   l = CosmicRayLabel(fname='/Users/nmiles/hst_cosmic_rays/data/WFPC2/'
                            'mastDownload/HST/u21y0a05t/u21y0a05t_c0m.fits',
                      gain_keyword='ATODGN*')
   l.run_ccd_label(deblend=False, use_dq=False, threshold_l=3, threshold_u=1000)



if __name__ == '__main__':
    main()
