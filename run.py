#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import db
from etsy import Etsy
from notifications import Gmail, Console

# logging
logging.basicConfig(filename='etsy.log',format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

ENV = os.environ

ETSY = Etsy(client_key=os.environ['ETSY_CLIENT_KEY'],
            client_secret=os.environ['ETSY_CLIENT_SECRET'],
            resource_owner_key=os.environ['ETSY_RESOURCE_OWNER_KEY'],
            resource_owner_secret=os.environ['ETSY_RESOURCE_OWNER_SECRET'])

def watch(url, url_params, handler, interval):
    while True:
        results = ETSY.get_data(url, url_params)['results']
        logging.debug('API fetched %s items from %s', len(results), url)

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
