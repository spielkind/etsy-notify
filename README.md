# etsy-notify

This is a tool that is meant to watch Etsy shop listings for significant changes and notify interested parties.

It does that by polling the Etsy API, analyzing the response and identifying any items that are new in the shop, either brand-new ones or any that have re-appeared. A notification is sent for all new items.

It is meant to run unattended on a small device like a Rasperry Pi.

*Note:* Currently only a single shop can be watched, and only GMail can be used for email notifications.

## Prerequesites
This tool expects Python version 3.5+ and uses `pipenv` for dependency management. If you don't have `pipenv`, install it like this:

    sudo pip install pipenv

or, on the Windows command line (if necessary, as Admin):

    pip install pipenv

As soon as `pipenv` is available, all other dependencies can be installed with:

    pipenv update

## Configuration
Place a text file named `.env` in in the project directory and put your [Etsy API keys](https://help.etsy.com/hc/en-us/articles/360000336247-Etsy-s-API) and [Google App passwords](https://support.google.com/accounts/answer/185833?hl=en) into that file.

```
ETSY_CLIENT_KEY="..."
ETSY_CLIENT_SECRET="..."
ETSY_RESOURCE_OWNER_KEY="..."
ETSY_RESOURCE_OWNER_SECRET="..."

ETSY_API_ENDPOINT="https://api.etsy.com/v2/"

GMAIL_USER='...@gmail.com'
GMAIL_PASSWORD='...'
```

`pipenv` will automatically load these values into environment variables.

## Running

To run the tool, either load the Python environment first (for debugging/testing)

    pipenv shell
    python ./run.py

...or use a single command (e.g. for chron jobs/scheduled tasks):

    pipenv run python ./run.py

## Bugs
Very probably.