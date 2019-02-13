#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import logging
from json import JSONDecodeError
from requests_oauthlib import OAuth1Session

class Etsy:
    def __init__(self, client_key, client_secret, resource_owner_key, resource_owner_secret):
        """sets up the OAuth session to use with the API"""

        self.session = OAuth1Session(client_key, client_secret,
                                     resource_owner_key, resource_owner_secret)

    def get(self, url, params):
        """gets any URL from the API"""

        url = os.environ['ETSY_API_ENDPOINT'] + url
        logging.debug('Etsy API: GET %s', url)
        response = self.session.get(url, params=params)

        if response.status_code == 200:
            return response

        logging.fatal('Unexpected status code %s from URL %s (%s)',
                      response.status_code, url, response.text)

    def get_data(self, url, params):
        """gets data from a URL, expects response in JSON format"""

        response = self.get(url, params)
        if response:
            try:
                return response.json()
            except JSONDecodeError:
                logging.fatal('Invalid JSON returned: "%s"', response.text)
                raise SystemExit(1)
        else:
            logging.fatal('No data available from request.')
            raise SystemExit(1)
