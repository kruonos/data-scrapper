# Data Scrapper

This repository contains a simple static webpage for querying the [Printpost letter API](https://api.printpost.com.br/v1/letter/consult-ar/).

Open `index.html` in a browser, enter a tracking code such as `YQ694556119BR` and your API key, then click **Consult** to see the API response.

The page sends the request with the provided `X-Api-Key` header and displays either the JSON response or an error message.
