# Data Scrapper

This repository contains a simple static webpage for querying the [Printpost letter API](https://api.printpost.com.br/v1/letter/consult-ar/).

Open `index.html` in a browser, enter a tracking code such as `YQ694556119BR` and your API key, then click **Consult** to see the API response.

The page sends the request with the provided `X-Api-Key` header and displays either the JSON response or an error message.

## Automatic AR download and OCR

The repository now also includes a Node.js automation that logs into the Correios SGD portal, downloads the AR images and performs OCR to extract the return reason for each tracking code.

### Prerequisites

1. Install dependencies:

   ```bash
   npm install
   ```

2. (Optional) export different credentials if you do not want to use the default ones baked into the script:

   ```bash
   export SGD_USERNAME="gpp159753."
   export SGD_PASSWORD="C159@753"
   ```

### Running the scraper

Execute the helper script with the desired options:

```bash
npm run fetch-ar -- --limit 5 --output output --input tracking-codes.txt
```

Key options:

* `--input` / `-i`: path to a text file containing one tracking code per line (defaults to `tracking-codes.txt`).
* `--codes`: comma-separated list of codes to process (overrides the input file).
* `--limit` / `-l`: process only the first _N_ codes.
* `--output` / `-o`: directory for downloaded images, OCR text and consolidated reports (default: `output`).
* `--skip-ocr`: downloads the AR images without running OCR.
* `--username` / `--password`: override the login credentials.
* `--concurrency`: parallel downloads/OCR workers (default: `3`).

The script produces:

* `output/images/<code>.jpg`: raw AR image for each processed object.
* `output/ocr/<code>.txt`: OCR text (omitted when `--skip-ocr` is used).
* `output/results.csv` and `output/results.json`: summaries containing either the extracted reason or the encountered error.

Language data for Tesseract is downloaded on demand and cached under `output/tesseract-data/` so subsequent runs are faster.
