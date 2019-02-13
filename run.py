#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import logging
from etsy import Etsy
from notifications import Gmail, Console

# logging
logging.basicConfig(filename='etsy.log', format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

ENV = os.environ

ETSY = Etsy(client_key=ENV['ETSY_CLIENT_KEY'],
            client_secret=ENV['ETSY_CLIENT_SECRET'],
            resource_owner_key=ENV['ETSY_RESOURCE_OWNER_KEY'],
            resource_owner_secret=ENV['ETSY_RESOURCE_OWNER_SECRET'])

if __name__ == "__main__":
    #HANDLER = Gmail(user=ENV['GMAIL_USER'],
    #                password=ENV['GMAIL_PASSWORD'],
    #                sent_from='XXX XXXXXX <XXXXXXX@gmail.com>',
    #                sent_to=['XXXXXX@gmail.com','XXXXXXX@gmail.com'])

    HANDLER = Console()

    ETSY.watch('shops/XXXXXXX/listings/active', url_params={
        'sort_on': 'created',
        'sort_order': 'down',
        'limit': 200
    }, handler=HANDLER, interval=60)
