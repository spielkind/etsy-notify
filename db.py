#!/usr/bin/python
# -*- coding: utf-8 -*-

import time
import sqlite3
import json

DB = sqlite3.connect('etsy.db')

"""initializes the dateabase if necesssary"""
DB.executescript(
    """
    CREATE TABLE IF NOT EXISTS `listings` (
        `listing_id`    INTEGER NOT NULL,
        `request_date`  INTEGER NOT NULL,
        `notified_date` INTEGER,
        `result`    TEXT,
        PRIMARY KEY(`listing_id`)
    );
    """)
DB.commit()

def unixtime():
    return int(time.time())

def placeholders(count):
    return ','.join('?' * count)

def store_listing(listing):
    """Insert (or update) a listing""" 
    params = (listing['listing_id'], unixtime(), json.dumps(listing))

    DB.execute("""
        UPDATE listings
        SET request_date = ?2, result = ?3
        WHERE listing_id = ?1;
    """, params)

    DB.execute("""
        INSERT INTO listings (listing_id, request_date, result)
        SELECT ?1, ?2, ?3
        WHERE NOT EXISTS (SELECT 1 FROM listings WHERE listing_id = ?1);
    """, params)

    DB.commit()

def get_diff_listings(listings):
    """remove inactive listings and return the ones that have not yet been notified"""

    listings = list(listings)
    listings_ids = [item['listing_id'] for item in listings]

    for listing in listings:
        store_listing(listing)

    DB.execute(
        """
        DELETE FROM listings
        WHERE listing_id NOT IN (""" + placeholders(len(listings_ids)) + """)
        AND notified_date IS NOT NULL;
        """, listings_ids)
    DB.commit()

    sql = "SELECT result FROM listings WHERE notified_date IS NULL;"
    return [json.loads(row[0]) for row in DB.execute(sql)]

def mark_as_notified(listings):
    """mark all given listings as 'notified' in the database"""

    listings_ids = [item['listing_id'] for item in listings]

    DB.executemany(
        """
        UPDATE listings
        SET    notified_date = ?
        WHERE  listing_id = ? AND notified_date IS NULL;
        """, [(unixtime(), id) for id in listings_ids])

    DB.commit()
