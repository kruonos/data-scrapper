# Data Scrapper

This repository provides a small toolkit for working with Correios AR data. It includes a web interface for quick checks and a Node.js automation that logs into the Correios SGD portal, downloads AR images and optionally performs OCR to extract the return reason for each tracking code.

## Using the web interface

1. Install dependencies (needed for both the automation and the local web server):

   ```bash
   npm install
   ```

2. Start the development server:

   ```bash
   npm start
   ```

3. Open <http://localhost:3000> in your browser.

4. Use the **Consult Printpost AR API** section to submit a tracking code and Printpost API key. The page forwards the request with the provided `X-Api-Key` header and displays either the JSON response or an error message.

5. Use the **Download Correios AR Images & OCR** section to enter your Correios SGD username, password and the list of tracking codes (one per line). When you submit the form the browser sends the credentials only to your local server, which runs the automation and saves the artefacts under `output/web/`.

Credentials are not stored anywhere in the repository; you must supply them each time you run the tool.

## Automatic AR download and OCR (CLI)

You can also run the automation directly from the command line. This is useful for scripting or when you do not need the browser-based interface.

### Prerequisites

1. Install dependencies if you have not already (`npm install`).
2. Provide your Correios SGD credentials either via environment variables or CLI flags:

   ```bash
   export SGD_USERNAME="<your-username>"
   export SGD_PASSWORD="<your-password>"



1. Install dependencies (needed for both the automation and the local web server):

   ```bash
   npm install
   ```

2. Start the development server:

   ```bash
   npm start
   ```

3. Open <http://localhost:3000> in your browser.

4. Use the **Consult Printpost AR API** section to submit a tracking code and Printpost API key. The page forwards the request with the provided `X-Api-Key` header and displays either the JSON response or an error message.

5. Use the **Download Correios AR Images & OCR** section to enter your Correios SGD username, password and the list of tracking codes (one per line). When you submit the form the browser sends the credentials only to your local server, which runs the automation and saves the artefacts under `output/web/`.

Credentials are not stored anywhere in the repository; you must supply them each time you run the tool.

## Automatic AR download and OCR (CLI)

You can also run the automation directly from the command line. This is useful for scripting or when you do not need the browser-based interface.

### Prerequisites

1. Install dependencies if you have not already (`npm install`).
2. Provide your Correios SGD credentials either via environment variables or CLI flags:

   ```bash
   export SGD_USERNAME="<your-username>"
   export SGD_PASSWORD="<your-password>"

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

=======

Execute the helper script with the desired options. Make sure the automation knows your credentials by either exporting the environment variables above or passing `--username` and `--password` flags:

```bash
npm run fetch-ar -- --limit 5 --output output --input tracking-codes.txt --username "$SGD_USERNAME" --password "$SGD_PASSWORD"

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
* `--username` / `--password`: Correios SGD credentials (required unless set via environment variables).


* `--username` / `--password`: Correios SGD credentials (required unless set via environment variables).
* `--username` / `--password`: override the login credentials.
* `--concurrency`: parallel downloads/OCR workers (default: `3`).

The script produces:

* `output/images/<code>.jpg`: raw AR image for each processed object.
* `output/ocr/<code>.txt`: OCR text (omitted when `--skip-ocr` is used).
* `output/results.csv` and `output/results.json`: summaries containing either the extracted reason or the encountered error.

Language data for Tesseract is downloaded on demand and cached under `output/tesseract-data/` so subsequent runs are faster.
