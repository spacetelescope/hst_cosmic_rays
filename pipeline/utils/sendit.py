#!/usr/bin/env python

from collections import defaultdict
from email.message import EmailMessage
from email.headerregistry import Address
from email.utils import make_msgid
import smtplib

import numpy as np
import pandas as pd

class Emailer(object):

    def __init__(self, cr_stats=None, file_metadata=None,
                 instr=None, processing_times=None):
        """


        Parameters
        ----------
        cr_stats : list
            List of `dict` containing of cosmic ray statistics to write out

        file_metadata : list
            List of file metadata objects

        instr : str
            Name of the instrument

        """

        self._cr_stats = cr_stats
        self._file_metadata = file_metadata
        self._instr = instr
        self._processing_times = processing_times

        self._body_text = None
        self._subject = None
        self._sender = None
        self._recipient = None


    @property
    def cr_stats(self):
        """:py:class:`~stat_utils.statshandler.ComputeStats`
                    object containing all the statistics to write out"""
        return self._cr_stats

    @property
    def file_metadata(self):
        """A list of :py:class:`~utils.metadata.GenerateMetadata` objects"""
        return self._file_metadata

    @property
    def instr(self):
        """One of the valid instrument names"""
        return self._instr

    @property
    def body_text(self):
        """Message to send in the email"""
        return self._body_text

    @body_text.setter
    def body_text(self, value):
        self._body_text = value

    @property
    def processing_times(self):
        """Processing self.processing_times for each step"""
        return self._processing_times

    @property
    def subject(self):
        """Subject of the email"""
        return self._subject

    @subject.setter
    def subject(self, value):
        self._subject = value

    @property
    def sender(self):
        """Person from whom the email is sent"""
        return self._sender

    @sender.setter
    def sender(self, value):
        """Person from whom the email is sent"""
        self._sender = value

    @property
    def recipient(self):
        """Person to whom the email is sent"""
        return self._recipient


    @recipient.setter
    def recipient(self, value):
        self._recipient = value


    def get_message_data(self):
        msg_data = defaultdict(list)

        for cr_stat, file_info in zip(self.cr_stats, self.file_metadata):

            msg_data['date'].append(file_info.metadata['date'])
            msg_data['avg_shape'].append(np.nanmean(cr_stat['shapes']))

            msg_data['avg_size [sigma]'].append(np.nanmean(cr_stat['sizes'][0]))

            msg_data['avg_size [pix]'].append(np.nanmean(cr_stat['sizes'][1]))

            msg_data['avg_energy_deposited [e]'].append(
                np.nanmean(cr_stat['energy_deposited'])
            )
            msg_data['CR count'].append(len(cr_stat['energy_deposited']))

        df = pd.DataFrame(msg_data)
        df = df.set_index(keys=['date'], drop=True)
        df.sort_index(inplace=True)
        return df

    def get_style(self):
        """ Generate style format for pd.DataFrame to be used in html conversion

        Parameters
        ----------
        self

        Returns
        -------

        """
        # Set CSS properties for th elements in dataframe
        th_props = [
            ('font-size', '14px'),
            ('text-align', 'center'),
            ('font-weight', 'bold'),
            ('color', 'black'),
            ('background-color', 'LightGray'),
            ('border', '1px solid black')
        ]

        # Set CSS properties for td elements in dataframe
        td_props = [
            ('font-size', '14px'),
            ('text-align', 'center'),
            ('border', '1px solid black')
        ]

        # Set table styles
        styles = [
            dict(selector="th", props=th_props),
            dict(selector="td", props=td_props)
        ]
        return styles

    def highlight_max(self, s):
        """ highlight the max value in the series with dark red

        Parameters
        ----------
        s

        Returns
        -------

        """
        is_max = s == s.max()
        return ['background-color: #DC143C' if v else '' for v in is_max]

    def highlight_min(self,s):
        """ Highlight the min value in the series with dark blue

        Parameters
        ----------
        s

        Returns
        -------

        """
        is_min = s == s.min()
        return ['background-color: #1E90FF' if v else '' for v in is_min]

    def low_outliers(self, s):
        """ Highlight outliers below the mean with light blue

        Parameters
        ----------
        s : pd.Series with

        Returns
        -------

        """
        med = s.median()
        std = s.std()
        flags = s < med - 1.25 * std
        return ['background-color: #87CEEB' if a else '' for a in flags]

    def high_outliers(self, s):
        """ Highlight outliers above the mean with light red

        Parameters
        ----------
        s

        Returns
        -------

        """
        med = s.median()
        std = s.std()
        flags = s > med + 1.25 * std
        return ['background-color: #CD5C5CC' if a else '' for a in flags]

    def SendEmail(self, gif_file=None, gif=False):
        """Send out an html markup email with an embedded gif and table

        Parameters
        ----------
        toSubj: email subject line
        data_for_email: data to render into an html table
        gif_file:

        Returns
        -------

        """
        css = self.get_style()
        df = self.get_message_data()

        s = (df.style
             .apply(self.high_outliers, subset=['avg_shape',
                                                'avg_size [pix]',
                                                'avg_size [sigma]',
                                                'avg_energy_deposited',
                                                'CR count'])
             .apply(self.low_outliers, subset=['avg_shape',
                                               'avg_size [pix]',
                                               'avg_size [sigma]',
                                               'avg_energy_deposited',
                                               'CR count'])
             .apply(self.highlight_max, subset=['avg_shape',
                                                'avg_size [pix]',
                                                'avg_size [sigma]',
                                                'avg_energy_deposited',
                                                'CR count'])
             .apply(self.highlight_min, subset=['avg_shape',
                                                'avg_size [pix]',
                                                'avg_size [sigma]',
                                                'avg_energy_deposited',
                                                'CR count'])

             .set_properties(**{'text-align': 'center'})
             .format({'avg_shape': '{:.2f}',
                      'avg_size [pix]': '{:.2f}',
                      'avg_size [sigma]': '{:.2f}',
                      'avg_energy_deposited': '{:.2f}'})
             .set_table_styles(css)
             )
        html_tb = s.render(index=False)
        msg = EmailMessage()
        msg['Subject'] = self.subject
        msg['From'] = Address('','nmiles', 'stsci.edu')
        msg['To'] = Address('', 'nmiles', 'stsci.edu')
        gif_cid = make_msgid()
        if gif:
            body_str = """
            <html>
                <head></head>
                <body>
                    <h2>Processing Times</h2>
                    <ul>
                        <li>Downloading data: {:.3f} minutes </li>
                        <li>CR rejection: {:.3f} minutes</li>
                        <li>Labeling analysis: {:.3f} minutes </li>
                        <li>Total time: {:.3f} minutes </li>
                    </ul>
                    <h2> Cosmic Ray Statistics </h2>
                    <p><b> All cosmic ray statistics reported are averages for 
                    the entire image</b></p>
                    <p><b> All cosmic ray statistics reported are averages for 
                            the entire image</b></p>
                    {}
                    <img src="cid:{}">
                </body>
            </html>
            """.format(self.processing_times['download'],
                       self.processing_times['cr_rejection'],
                       self.processing_times['analysis'],
                       self.processing_times['total'],
                       html_tb,
                       gif_cid[1:-1])
            msg.add_alternative(body_str, subtype='html', )
        else:
            body_str = """
                    <html>
                        <head></head>
                        <body>
                        <h2>Processing Times</h2>
                            <ul>
                                <li>Downloading data: {:.3f} minutes </li>
                                <li>CR rejection: {:.3f} minutes</li>
                                <li>Labeling analysis: {:.3f} minutes </li>
                                <li>Total time: {:.3f} minutes </li>
                            </ul>
                        <h2> Cosmic Ray Statistics </h2>
                        <p><b> All cosmic ray statistics reported are averages for 
                                the entire image</b></p>
                                {}
                        </body>
                    </html>
                    """.format(self.processing_times['download'],
                               self.processing_times['cr_rejection'],
                               self.processing_times['analysis'],
                               self.processing_times['total'],
                               html_tb)
            msg.add_alternative(body_str, subtype='html')
        if gif:
            with open(gif_file, 'rb') as img:
                msg.get_payload()[0].add_related(img.read(), 'image', 'gif',
                                                 cid=gif_cid)

        msg.add_alternative(body_str, subtype='html')

        with smtplib.SMTP('smtp.stsci.edu') as s:
            s.send_message(msg)



if __name__ == '__main__':
    e = Emailer()