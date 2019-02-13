#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import time
import logging
from json import JSONDecodeError
from requests_oauthlib import OAuth1Session
from notifications import Gmail, Console
import db

ENV = os.environ

ETSY = OAuth1Session(ENV['ETSY_CLIENT_KEY'],
                     client_secret=ENV['ETSY_CLIENT_SECRET'],
                     resource_owner_key=ENV['ETSY_RESOURCE_OWNER_KEY'],
                     resource_owner_secret=ENV['ETSY_RESOURCE_OWNER_SECRET'])

# logging
logging.basicConfig(filename='etsy.log',format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

def watch(url, url_params, handler, interval):
    while True:
        response = ETSY.get(ENV['ETSY_API_ENDPOINT'] + url, params=url_params)

        if response.status_code == 200:
            try:
                results = response.json()['results']
            except JSONDecodeError:
                logging.fatal('Invalid JSON returned from URL %s: "%s"', url, response.text)
                break
        else:
            logging.fatal('Unexpected status code %s from URL %s (%s)', 
                          response.status_code, url, response.text)
            break

        logging.info('API fetched %s items from %s', len(results), url)

        db.store_listings(results)
        new_items = db.get_diff_listings(results)

        if new_items:
            handler.nodify_items(new_items)
            db.mark_as_notified(new_items)
            logging.info("notified %s new items", len(new_items))
        else:
            logging.info("no new items this time")

        time.sleep(interval)

if __name__ == "__main__":
    #HANDLER = Gmail(user=ENV['GMAIL_USER'],
    #                password=ENV['GMAIL_PASSWORD'],
    #                sent_from='XXX XXXXXX <XXXXXXX@gmail.com>',
    #                sent_to=['XXXXXX@gmail.com','XXXXXXX@gmail.com'])

    HANDLER = Console()

    watch('shops/XXXXXXX/listings/active', url_params={
        'sort_on': 'created',
        'sort_order': 'down',
        'limit': 200
    }, handler=HANDLER, interval=60)
