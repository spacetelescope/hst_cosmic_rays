#!/usr/bin/env python

from astropy.io import fits

from astropy.stats import sigma_clipped_stats

from label.base_label import Label

import numpy as np

from scipy import ndimage


class CosmicRayLabel(Label):
    """
    Class for generating the cosmic ray label
    """
    def __init__(self, fname, instr, instr_cfg, ccd=None, ir=None):
        super().__init__(fname)

        self.instr = instr
        self.instr_cfg = instr_cfg
        self.ccd = ccd
        self.ir = ir


    def run_ccd_label(self, deblend=False, use_dq=True, extnums=[1,2],
                      threshold_l=None, threshold_u=None, plot=False):
        """ Run labeling algorithm on CCD data

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
        # Get the DQ array
        self.get_data(extname='dq', extnums=extnums)

        # Get the SCI array
        self.get_data(extname='sci', extnums=extnums)

        self.get_ccd_label(use_dq = use_dq,
                           threshold_l=threshold_l,
                           deblend=deblend,
                           threshold_u=threshold_u)

        if plot:
            self.plot(show=True)




def main():
   l = CosmicRayLabel(fname='/Users/nmiles/hst_cosmic_rays/data/'
                            'STIS/CCD/mastDownload/HST/o3st06ekq'
                            '/o3st06ekq_flt.fits')
   l.run_ccd_label(deblend=False, use_dq=True, threshold_l=3, threshold_u=1000)



if __name__ == '__main__':
    main()
