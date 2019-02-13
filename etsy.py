#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import time
import logging
from json import JSONDecodeError
from requests_oauthlib import OAuth1Session
import db

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

    def watch(self, url, url_params, handler, interval):
        """starts polling a shop URL in a given interval""" 

        while True:
            results = self.get_data(url, url_params)['results']
            logging.debug('API fetched %s items from %s', len(results), url)

            new_items = db.get_diff_listings(results)

            if new_items:
                handler.nodify_items(new_items)
                db.mark_as_notified(new_items)
                logging.info("notified %s new items", len(new_items))
            else:
                logging.info("no new items this time")

            time.sleep(interval)
