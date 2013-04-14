import base64
import html.parser
import http.client
import logging
import os
import random
import re
import sqlite3
import sys
import time
import argparse


_logger = logging.getLogger(__name__)


class VisibliHexURLGrab(object):
    def __init__(self, sequential=True):
        self.db = sqlite3.connect('visibli.db')
        self.db.execute('PRAGMA journal_mode=WAL')

        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS visibli_hex
            (shortcode BLOB PRIMARY KEY, url TEXT, not_exist INTEGER)
            ''')

        self.http_client = http.client.HTTPConnection('links.sharedby.co')
        self.throttle_time = 1
        self.sequential = sequential
        self.seq_num = 0

    def new_shortcode(self):
        while True:
            if self.sequential:
                s = '{:06x}'.format(self.seq_num)
                shortcode = base64.b16decode(s.encode(), casefold=True)
                self.seq_num += 1

                if self.seq_num > 0xffffff:
                    raise Exception('No more short codes')
            else:
                shortcode = os.urandom(3)

            rows = self.db.execute('SELECT 1 FROM visibli_hex WHERE '
                'shortcode = ? LIMIT 1', [shortcode])

            if not len(list(rows)):
                return shortcode

    def run(self):
        while True:
            self.fetch_url()
            t = random.triangular(0, 2, 0)
            _logger.debug('Sleep %s', t)
            time.sleep(t)

    def fetch_url(self):
        shortcode = self.new_shortcode()

        shortcode_str = base64.b16encode(shortcode).lower().decode()
        path = '/links/{}'.format(shortcode_str)

        _logger.info('Begin fetch URL %s', path)

        self.http_client.request('GET', path)

        response = self.http_client.getresponse()

        url = self.read_response(response)

        if not url:
            self.add_no_url(shortcode)
        else:
            self.add_url(shortcode, url)

        self.throttle(response.status)

    def read_response(self, response):
        _logger.debug('Got status %s %s', response.status, response.reason)

        data = response.read()
        assert isinstance(data, bytes)

        if response.status == 301:
            url = response.getheader('Location')
            return url
        elif response.status == 200:
            match = re.search(br'<iframe id="[^"]+" src="([^"]+)">', data)

            if not match:
                _logger.warning('No iframe found')
                return

            url = match.group(1).decode()
            url = html.parser.HTMLParser().unescape(url)

            return url

    def throttle(self, status_code):
        if 400 <= status_code <= 499 or 500 <= status_code <= 999:
            _logger.info('Throttle %d seconds', self.throttle_time)
            time.sleep(self.throttle_time)

            self.throttle_time *= 2
            self.throttle_time = min(3600, self.throttle_time)
        else:
            self.throttle_time /= 2
            self.throttle_time = min(600, self.throttle_time)
            self.throttle_time = max(1, self.throttle_time)

    def add_url(self, shortcode, url):
        _logger.debug('Insert %s %s', shortcode, url)
        with self.db:
            self.db.execute('INSERT INTO visibli_hex VALUES (?, ?, ?)',
                [shortcode, url, None])

    def add_no_url(self, shortcode):
        _logger.debug('Mark no url %s', shortcode)
        with self.db:
            self.db.execute('INSERT INTO visibli_hex VALUES (?, ?, ?)',
                [shortcode, None, 1])

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--sequential', action='store_true')
    args = arg_parser.parse_args()
    logging.basicConfig(level=logging.DEBUG)
    o = VisibliHexURLGrab(sequential=args.sequential)
    o.run()
