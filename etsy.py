#!/usr/bin/python3

import os
import time
import smtplib
import logging
import sqlite3
import json
from datetime import datetime
from requests_oauthlib import OAuth1Session

ENV = os.environ

etsy = OAuth1Session(ENV['ETSY_CLIENT_KEY'],
                     client_secret=ENV['ETSY_CLIENT_SECRET'],
                     resource_owner_key=ENV['ETSY_RESOURCE_OWNER_KEY'],
                     resource_owner_secret=ENV['ETSY_RESOURCE_OWNER_SECRET'])

url = ENV['ETSY_API_ENDPOINT'] + 'shops/XXXXXXX/listings/active?sort_on=created&sort_order=down&limit=200'

# logging
logging.basicConfig(filename='/home/XXXXX/etsy/etsy.log',format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO)

# console handler
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger("").addHandler(console)

def notify(items):
    if not items:
        return
    gmail_user = ENV['GMAIL_USER']
    gmail_password = ENV['GMAIL_PASSWORD']
    sent_from = 'XXX XXXXXX <XXXXXXX@gmail.com>'
    sent_to = ['XXXXXX@gmail.com','XXXXXXX@gmail.com']
    subject = 'At least one new Etsy item in XXXXX shop is available!'
    body = 'Hey, at least one new Etsy item is available:\n'
    for i in items:
        ts = datetime.fromtimestamp(i['last_modified_tsz']).strftime('%H:%M:%S %d.%m.%Y')
        body += 'Date: ' + ts + '\nTitle: ' +  i['title'] + '\nURL: ' + i['url'] + '\n'
    headers = {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Disposition': 'inline',
      'Content-Transfer-Encoding': '8bit',
      'From': sent_from,
      'To': ", ".join(sent_to),
      'Date': datetime.now().strftime('%a, %d %b %Y  %H:%M:%S %Z'),
      'X-Mailer': 'python',
      'Subject': subject
    }
    msg = ''
    for key, value in headers.items():
        msg += "%s: %s\n" % (key, value)
    msg += '\n' + body

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.ehlo()
        server.login(gmail_user, gmail_password)
        server.sendmail(headers['From'], headers['To'], msg.encode('utf8'))
        logging.info(msg)
        server.close()

        logging.info('Email sent!')
    except Exception as e:
        logging.exception('Something went wrong...\n' + e)

def unixtime():
    return int(time.time())

conn = sqlite3.connect('/home/pi/etsy/etsy.db')
db = conn.cursor()
db.execute("""
    CREATE TABLE IF NOT EXISTS `listings` (
        `listing_id`    INTEGER NOT NULL,
        `request_date`  INTEGER NOT NULL,
        `notified_date` INTEGER,
        `result`    TEXT,
        PRIMARY KEY(`listing_id`)
    );
""")

while True:
    current_ts = unixtime()
    results = etsy.get(url).json()['results']
    listings_ids = [item['listing_id'] for item in results]

    # insert or update listings for this request
    for result in results:
        params = (result['listing_id'], current_ts, json.dumps(result))
        db.execute("""
          UPDATE listings
          SET request_date = :2, result = :3
          WHERE listing_id = :1;
        """, params)

        db.execute("""
          INSERT INTO listings (listing_id, request_date, result)
          SELECT :1, :2, :3
          WHERE NOT EXISTS (SELECT 1 FROM listings WHERE listing_id = :1);
        """, params)

    conn.commit()
    logging.info('API fetched TS: %s', current_ts)

    # delete any listing that is no longer part of this request (and has been notified)
    sql = ("DELETE FROM listings"
           " WHERE listing_id NOT IN (" + ','.join('?'*len(listings_ids)) + ")"
           " AND notified_date IS NOT NULL;")
    sql_result = db.execute(sql, listings_ids)

    # select remaining unnotified listings & notify
    sql = "SELECT result FROM listings WHERE notified_date IS NULL;"
    sql_result = db.execute(sql)
    items = [json.loads(row[0]) for row in sql_result]

    notify(items)
    db.executemany("""
      UPDATE listings SET notified_date = ? WHERE listing_id = ? AND notified_date IS NULL;
    """, [(unixtime(), item['listing_id']) for item in items]
    )
    conn.commit()

    time.sleep(60)

conn.close()
