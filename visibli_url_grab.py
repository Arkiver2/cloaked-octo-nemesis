'''Grab Visibli hex shortcodes'''
# Copyright 2013 Christopher Foo <chris.foo@gmail.com>
# Licensed under GPLv3. See COPYING.txt for details.
import argparse
import base64
import collections
import gzip
import html.parser
import http.client
import logging
import logging.handlers
import os
import random
import re
import sqlite3
import time


_logger = logging.getLogger(__name__)


class UnexpectedResult(ValueError):
    pass


class VisibliHexURLGrab(object):
    def __init__(self, sequential=False, reverse_sequential=False,
    sleep_time_max=2, database_dir=''):
        self.db = sqlite3.connect(os.path.join(database_dir, 'visibli.db'))
        self.db.execute('PRAGMA journal_mode=WAL')

        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS visibli_hex
            (shortcode BLOB PRIMARY KEY, url TEXT, not_exist INTEGER)
            ''')

        self.http_client = http.client.HTTPConnection('links.sharedby.co')
        self.throttle_time = 1
        self.sequential = sequential
        self.reverse_sequential = reverse_sequential
        self.seq_num = 0xffffff if self.reverse_sequential else 0
        self.session_count = 0
        self.total_count = self.get_count() or 0
        self.sleep_time_max = sleep_time_max
        self.headers = {
            'User-Agent': 'ZGDBGLQ (gzip)',
            'Accept-Encoding': 'gzip',
        }
        self.average_deque = collections.deque(maxlen=100)

    def new_shortcode(self):
        while True:
            if self.sequential or self.reverse_sequential:
                s = '{:06x}'.format(self.seq_num)
                shortcode = base64.b16decode(s.encode(), casefold=True)

                if self.reverse_sequential:
                    self.seq_num -= 1

                    if self.seq_num < 0:
                        raise Exception('No more short codes')
                else:
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
            try:
                self.fetch_url()
            except http.client.HTTPException:
                _logger.exception('Got an http error.')
                self.http_client.close()
                time.sleep(120)
                continue
            except UnexpectedResult as e:
                _logger.warn('Unexpected result %s', e)
                self.throttle(None, force=True)
                continue
            self.session_count += 1
            t = random.triangular(0, self.sleep_time_max, 0)

            if self.session_count % 10 == 0:
                _logger.info('Session={}, total={}, {:.3f} u/s'.format(
                    self.session_count, self.session_count + self.total_count,
                    self.calc_avg()))

            _logger.debug('Sleep {:.3f}'.format(t))
            time.sleep(t)

    def fetch_url(self):
        shortcode = self.new_shortcode()

        shortcode_str = base64.b16encode(shortcode).lower().decode()
        path = '/links/{}'.format(shortcode_str)

        _logger.debug('Begin fetch URL %s', path)

        self.http_client.request('GET', path, headers=self.headers)

        response = self.http_client.getresponse()

        url = self.read_response(response)
        if not url:
            self.add_no_url(shortcode)
        else:
            self.add_url(shortcode, url)

        _logger.info('%s->%s...', shortcode_str,
            url[:30] if url else '(none)')

        self.throttle(response.status)

    def read_response(self, response):
        _logger.debug('Got status %s %s', response.status, response.reason)

        data = response.read()
        assert isinstance(data, bytes)

        if response.getheader('Content-Encoding') == 'gzip':
            _logger.debug('Got gzip data')
            data = gzip.decompress(data)

        if response.status == 301:
            url = response.getheader('Location')
            return url
        elif response.status == 200:
            match = re.search(br'<iframe id="[^"]+" src="([^"]+)">', data)

            if not match:
                raise UnexpectedResult('No iframe found')

            url = match.group(1).decode()
            url = html.parser.HTMLParser().unescape(url)

            return url
        elif response.status == 302:
            location = response.getheader('Location')

            if location and 'sharedby' not in location:
                raise UnexpectedResult(
                    'Weird 302 redirect to {}'.format(location))
            elif not location:
                raise UnexpectedResult('No redirect location')

            return
        else:
            raise UnexpectedResult('Unexpected status {}'.format(
                response.status))

    def throttle(self, status_code, force=False):
        if force or 400 <= status_code <= 499 or 500 <= status_code <= 999:
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

    def get_count(self):
        for row in self.db.execute('SELECT COUNT(ROWID) FROM visibli_hex '
        'LIMIT 1'):
            return int(row[0])

    def calc_avg(self):
        self.average_deque.append((self.session_count, time.time()))

        try:
            avg = ((self.session_count - self.average_deque[0][0])
                / (time.time() - self.average_deque[0][1]))
        except ArithmeticError:
            avg = 0

        return avg

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('--sequential', action='store_true')
    arg_parser.add_argument('--reverse-sequential', action='store_true')
    arg_parser.add_argument('--sleep-max', type=float, default=2.0)
    arg_parser.add_argument('--quiet', action='store_true')
    arg_parser.add_argument('--database-dir', default=os.getcwd())
    arg_parser.add_argument('--log-dir', default=os.getcwd())
    args = arg_parser.parse_args()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if not args.quiet:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(
            logging.Formatter('%(levelname)s %(message)s'))
        root_logger.addHandler(console)

    log_filename = os.path.join(args.log_dir, 'visibli_url_grab.log')
    file_log = logging.handlers.RotatingFileHandler(log_filename,
        maxBytes=1048576, backupCount=9)
    file_log.setLevel(logging.DEBUG)
    file_log.setFormatter(logging.Formatter(
        '%(asctime)s %(name)s:%(lineno)d %(levelname)s %(message)s'))
    root_logger.addHandler(file_log)

    o = VisibliHexURLGrab(sequential=args.sequential,
        reverse_sequential=args.reverse_sequential,
        database_dir=args.database_dir,
        sleep_time_max=args.sleep_max)
    o.run()
