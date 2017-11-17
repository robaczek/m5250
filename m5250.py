#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Data retrieval module from TP-Link M5250 mobile 3g router.

This module does the tedious job of extracting information presented by
the router webUI and collects them into a single dictionary.
Useful for statistics collection or low battery alerts.
"""

from __future__ import print_function, unicode_literals

__license__ = "MIT"
__version__ = "0.1"
__author__  = "Wiktor Gołgowski"
__email__   = "wgolgowski@gmail.com"

import re
import base64

# Make urllib work under Python 2 and 3:
try:
    from urllib.request import urlopen, Request
except ImportError:
    from urllib2 import urlopen, Request

## These are the default values for out-of-the-box device:
DEFAULT_URL = "http://192.168.0.1/"
DEFAULT_LOGIN = 'admin'
DEFAULT_PASSWORD = 'admin'


class M5250:
    def __init__(self, url=DEFAULT_URL, login=DEFAULT_LOGIN, password=DEFAULT_PASSWORD):
        self.url = url
        if not self.url.endswith('/'):
            self.url += '/'
        self._session_id = '0'
        self._headers = {}
        self.data = {}

        self.authorize(login, password)

    @staticmethod
    def _dev_battery(devstatus):
        if devstatus[3] == 5:
            return "charging"
        elif devstatus[3] == 6:
            return "no battery"
        else:
            return devstatus[9]+'%'

    @staticmethod
    def _wan_link(wanstatus):
        if wanstatus[2] == '32':
            return 'connected'
        elif wanstatus[2] == '4':
            return 'connecting'
        elif wanstatus[2] == '0x40':
            return 'disconnecting'
        else:
            return 'disconnected'

    @staticmethod
    def _wan_network(wanstatus):
        if wanstatus[0] == '0':
            return 'no service'
        elif wanstatus[3] == '5':
            return 'UMTS'
        elif wanstatus[3] == '3':
            return 'UMTS Roaming'
        else:
            return 'no service'

    @staticmethod
    def _wan_sim(wanstatus):
        if wanstatus[0] == '0':
            return 'invalid'
        elif wanstatus[0] == '1':
            return 'ready'
        elif wanstatus[0] == '2':
            return 'pin required'
        elif wanstatus[0] == '3':
            return 'puk required'
        elif wanstatus[0] == '4':
            return 'pin verified'
        else:
            return 'unknown'

    @staticmethod
    def _wan_int2ip(ipint):
        return '.'.join(str(x) for x in [
            ipint & 0xff, (ipint>>8)&0xff, (ipint>>16)&0xff, (ipint>>24)&0xff
        ])

    def authorize(self, login, password):
        credentials = base64.b64encode(
            login.encode("utf-8")+b':'+password.encode("utf-8")
        ).decode('utf-8')
        self._headers = {
            "Cookie":"Authorization=Basic%%20%s; subType=pcSub; TPLoginTimes=1" % credentials
        }
        req = Request(self.url, headers=self._headers)
        response = urlopen(req)
        if response.getcode() != 200:
            raise RuntimeError('Got '+str(response.getcode())+' response.')
        main_content = response.read()
        session = re.search('var session_id = "(\d+)"', main_content.decode("utf-8"))
        if session is not None:
            session_match = session.group(1)
        else:
            raise RuntimeError('Authorization failed')
        if session_match == '0':
            raise RuntimeError('Authorization failed')
        else:
            self._session_id = session_match

    def get_device_data(self):
        if self._session_id == '0':
            raise RuntimeError('Unauthorized')
        req = Request(
            self.url+'userRpm/deviceStatus.htm?dataRequestOnly=1&session_id='+self._session_id,
            headers=self._headers
        )
        response = urlopen(req)
        if response.getcode() != 200:
            raise RuntimeError('Got '+str(response.getcode())+' response.')
        dev_content = response.read()
        devstatus = re.search(
            'var devStatusDataOnlyInfo = new Array\(([0-9\s,]*)\);',
            dev_content.decode("utf-8")
        )
        if devstatus is None:
            raise ValueError('Cannot parse page output.')
        self.dev = (''.join(devstatus.group(1).split())).split(',')
        self.data['battery'] = M5250._dev_battery(self.dev)
        self.data['sdcard'] = self.dev[4]
        self.data['signal'] = self.dev[7]+'%'
        self.data['wan'] = '0' if self.dev[2] == '32' else '1'
        # SMS incomplete, see devSmsFullInfo in JS sources.
        self.data['sms'] = 'none' if self.dev[0] == '0' else 'unread'
        # JS seems to always report WiFi connected.
        self.data['wifi'] = self.dev[5]

    def get_link_data(self):
        if self._session_id == '0':
            raise RuntimeError('Unauthorized')
        req = Request(
            self.url+'userRpm/linkStatus.htm?session_id='+self._session_id,
            headers=self._headers
        )
        response = urlopen(req)
        if response.getcode() != 200:
            raise RuntimeError('Got '+str(response.getcode())+' response.')
        link_content = response.read()
        wan_status = re.search(
            'var wwanStatusInfo = new Array\(([0-9\s,.A-Z\"]*)\);',
            link_content.decode("utf-8")
        )
        wifi_status = re.search(
            'var wifiStatusInfo = new Array\(([0-9a-zA-Z\",\s_\-]*)\);',
            link_content.decode("utf-8")
        )
        if wan_status is None or wifi_status is None:
            raise ValueError('Cannot parse page output.')
        self.wan = (''.join(wan_status.group(1).split())).split(',')
        self.wifi = (''.join(wifi_status.group(1).split())).split(',')

        self.data['wifi_ssid'] = self.wifi[3][1:-1]
        self.data['wifi_clients'] = self.wifi[0]
        self.data['wifi_channel'] = 'auto' if self.wifi[1] == '0' else self.wifi[1]
        self.data['wifi_security'] = 'none' if self.wifi[2] == '0' else 'wpa12psk'

        self.data['wan_link'] = M5250._wan_link(self.wan)
        self.data['wan_network'] = M5250._wan_network(self.wan)
        self.data['wan_sim'] = M5250._wan_sim(self.wan)

        # There are traces in the code suggesting that the data statistics
        # were calculated differently, as follows:
        #self.data['rx'] = self.wan[6]
        #self.data['tx'] = self.wan[4]
        #self.data['total_rx'] = self.wan[9]
        #self.data['total_tx'] = self.wan[11]
        # Now, they are transmitted directly:
        self.data['rx'] = self.wan[19]
        self.data['tx'] = self.wan[20]
        self.data['total_data'] = self.wan[18]
        self.data['duration_sec'] = self.wan[8] # in seconds, I hope.
        self.data['total_duration'] = self.wan[13]

        self.data['ip'] = M5250._wan_int2ip(int(self.wan[14]))
        self.data['dns1'] = M5250._wan_int2ip(int(self.wan[15]))
        self.data['dns2'] = M5250._wan_int2ip(int(self.wan[16]))
            


def main():
    m = M5250()
    m.get_device_data()
    m.get_link_data()
    print(m.data)

if __name__ == "__main__":
    main()
                    

