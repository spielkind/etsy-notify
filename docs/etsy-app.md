# Creating an Etsy app
Shop Notify only reads public listings, so it needs an API key but no OAuth login.

1. Log in to Etsy (a regular account is enough, you don't need a shop) and enable two-factor authentication under *Settings → Security*.
2. Open <https://www.etsy.com/developers/register> and fill in the form:
   - **Name**: anything *without* the word "etsy" (it is a restricted word), e.g. `shop-watcher-yourname`.
   - **Description**: e.g. "Personal tool that polls the active listings of a single shop and emails me when new items appear. Sends notification emails only to myself via my own mail account."
   - **Website URL**: the URL of this repository is fine.
   - **Type of application**: *Buyer Tools*
   - **Users**: *Just myself or colleagues*
   - **Commercial / charge for access**: *No*
   - **Will your app do any of the following**: leave all unchecked (it neither edits listings nor reads sales data, and it does not email Etsy members).
3. Open <https://www.etsy.com/developers/your-apps> → *See API Key Details* and copy the **keystring** and the **shared secret**.

New apps start as *Pending Personal Approval*. Until the status changes to **Active**, every request fails with `403 API key not found or not active` – approval can take from a few hours to several days.

Once the app is **Active**, check the key without starting the tool:

```sh
curl -s -H "x-api-key: KEYSTRING:SHARED_SECRET" \
  "https://openapi.etsy.com/v3/application/shops?shop_name=SHOPNAME" | jq '.results[0].shop_id'
```

A new app may make 5,000 requests per day and 5 per second; see [Choosing the poll interval](../README.md#choosing-the-poll-interval).
