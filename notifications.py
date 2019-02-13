#!/usr/bin/python3
# -*- coding: utf-8 -*-

import smtplib
import logging
from datetime import datetime

class Gmail:
    def __init__(self, user, password, sent_to, sent_from):
        self.user = user
        self.password = password
        self.sent_to = sent_to
        self.sent_from = sent_from

    def send(self, subject, body):
        headers = {
            'Content-Type': 'text/plain; charset=utf-8',
            'Content-Disposition': 'inline',
            'Content-Transfer-Encoding': '8bit',
            'From': self.sent_from,
            'To': ', '.join(self.sent_to),
            'Date': datetime.now().strftime('%a, %d %b %Y  %H:%M:%S %Z'),
            'X-Mailer': 'python',
            'Subject': subject
        }
        msg = ''
        for key, value in headers.items():
            msg += '%s: %s\n' % (key, value)
        msg += '\n' + body

        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.ehlo()
            server.login(self.user, self.password)
            server.sendmail(headers['From'], self.sent_to, msg.encode('utf8'))
            logging.info(msg)
            server.close()

            logging.info('Email sent!')
        except Exception as e:
            logging.exception('Failed to send email\n%s', e)

    def nodify_items(self, items):
        if not items:
            return

        subject = 'At least one new Etsy item in XXXXX shop is available!'
        body = 'Hey, at least one new Etsy item is available:\n'
        for i in items:
            ts = datetime.fromtimestamp(i['last_modified_tsz']).strftime('%H:%M:%S %d.%m.%Y')
            body += 'Date: ' + ts + '\nTitle: ' +  i['title'] + '\nURL: ' + i['url'] + '\n' 

        self.send(subject, body)

class Console:
    """ notifications to the console for debugging purposes"""
    @staticmethod
    def nodify_items(items):
        for item in items:
            print('NOTIFY: listing ID %s "%s"' % (item['listing_id'], item['title']))
