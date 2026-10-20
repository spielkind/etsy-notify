# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/spielkind/etsy-notify/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                              |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|---------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/etsy\_notify/\_\_init\_\_.py  |        0 |        0 |        0 |        0 |    100% |           |
| src/etsy\_notify/\_\_main\_\_.py  |       65 |        0 |       14 |        1 |     99% | 30-\>exit |
| src/etsy\_notify/config.py        |       37 |        0 |        4 |        0 |    100% |           |
| src/etsy\_notify/db.py            |       24 |        0 |        0 |        0 |    100% |           |
| src/etsy\_notify/etsy.py          |       69 |        1 |       12 |        1 |     98% |        88 |
| src/etsy\_notify/models.py        |        6 |        0 |        0 |        0 |    100% |           |
| src/etsy\_notify/notifications.py |       43 |        0 |        6 |        0 |    100% |           |
| **TOTAL**                         |  **244** |    **1** |   **36** |    **2** | **99%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/spielkind/etsy-notify/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/spielkind/etsy-notify/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/spielkind/etsy-notify/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/spielkind/etsy-notify/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fspielkind%2Fetsy-notify%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/spielkind/etsy-notify/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.