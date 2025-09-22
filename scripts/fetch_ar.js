#!/usr/bin/env node

const fs = require('fs/promises');
const path = require('path');
const process = require('process');
const http = require('http');
const https = require('https');
const zlib = require('zlib');
const { CookieJar } = require('tough-cookie');
const { fetch: undiciFetch, ProxyAgent: UndiciProxyAgent } = require('undici');
const sharp = require('sharp');
const cheerio = require('cheerio');
const Tesseract = require('tesseract.js');
const pLimit = require('p-limit').default;
const { ProxyAgent } = require('proxy-agent');

const DEFAULT_USERNAME = process.env.SGD_USERNAME || 'gpp159753.';
const DEFAULT_PASSWORD = process.env.SGD_PASSWORD || 'C159@753';
const DEFAULT_TRACKING_FILE = path.join(__dirname, '..', 'tracking-codes.txt');
const DEFAULT_OUTPUT_DIR = path.join(__dirname, '..', 'output');
const LOGIN_ENTRY_URL = 'https://sgd.correios.com.br/sgd/core/seguranca/entrar.php';
const AR_ENDPOINT = 'https://sgd.correios.com.br/sgd/app/objeto/objetos/verArDigital.php';

function parseArgs(argv) {
  const options = {
    inputFile: DEFAULT_TRACKING_FILE,
    outputDir: DEFAULT_OUTPUT_DIR,
    concurrency: 3,
    limit: Infinity,
    username: DEFAULT_USERNAME,
    password: DEFAULT_PASSWORD,
    codes: null,
    skipOcr: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    switch (arg) {
      case '--input':
      case '-i':
        options.inputFile = path.resolve(argv[++i]);
        break;
      case '--output':
      case '-o':
        options.outputDir = path.resolve(argv[++i]);
        break;
      case '--limit':
      case '-l':
        options.limit = Number(argv[++i]);
        break;
      case '--concurrency':
      case '-c':
        options.concurrency = Number(argv[++i]);
        break;
      case '--username':
      case '-u':
        options.username = argv[++i];
        break;
      case '--password':
      case '-p':
        options.password = argv[++i];
        break;
      case '--codes':
        options.codes = argv[++i].split(',').map((code) => code.trim()).filter(Boolean);
        break;
      case '--skip-ocr':
        options.skipOcr = true;
        break;
      default:
        if (arg.startsWith('--')) {
          throw new Error(`Unknown argument: ${arg}`);
        }
        break;
    }
  }

  if (Number.isNaN(options.limit) || options.limit <= 0) {
    options.limit = Infinity;
  }
  if (Number.isNaN(options.concurrency) || options.concurrency <= 0) {
    options.concurrency = 3;
  }
  return options;
}

async function loadTrackingCodes(options) {
  if (options.codes && options.codes.length) {
    return Array.from(new Set(options.codes));
  }
  const content = await fs.readFile(options.inputFile, 'utf8');
  const lines = content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return Array.from(new Set(lines));
}

function stripAccents(text) {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function extractReturnReason(text) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  if (!lines.length) {
    return '';
  }

  const keywords = [
    'MOTIVO',
    'DEVOL',
    'DESTINAT',
    'AUSENTE',
    'RECUS',
    'MUDOU',
    'NAO EXISTE',
    'NAO PROCURADO',
    'ENDERECO',
    'ENDEREÇO',
    'ENDERECO INSUF',
  ];

  for (let i = 0; i < lines.length; i += 1) {
    const original = lines[i];
    const normalized = stripAccents(original).toUpperCase();
    if (keywords.some((key) => normalized.includes(stripAccents(key).toUpperCase()))) {
      return original;
    }
    if (i < lines.length - 1) {
      const combined = `${original} ${lines[i + 1]}`.trim();
      const normalizedCombined = stripAccents(combined).toUpperCase();
      if (keywords.some((key) => normalizedCombined.includes(stripAccents(key).toUpperCase()))) {
        return combined;
      }
    }
  }

  return lines.slice(-3).join(' ');
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function gunzip(buffer) {
  return new Promise((resolve, reject) => {
    zlib.gunzip(buffer, (err, result) => {
      if (err) {
        reject(err);
      } else {
        resolve(result);
      }
    });
  });
}

async function ensureDirectories(baseDir) {
  const imagesDir = path.join(baseDir, 'images');
  const ocrDir = path.join(baseDir, 'ocr');
  await fs.mkdir(imagesDir, { recursive: true });
  await fs.mkdir(ocrDir, { recursive: true });
  return { imagesDir, ocrDir };
}

function createRequester(jar, proxyUrl) {
  const agent = proxyUrl ? new ProxyAgent(proxyUrl) : null;

  return async function doRequest(url, options = {}) {
    const {
      method = 'GET',
      headers = {},
      body,
      responseType = 'text',
    } = options;

    const finalHeaders = {
      'Accept-Encoding': 'identity',
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'User-Agent': 'Mozilla/5.0 (compatible; ARFetcher/1.0; +https://github.com/)',
      ...headers,
    };

    const cookieHeader = await jar.getCookieString(url);
    if (cookieHeader) {
      finalHeaders.Cookie = cookieHeader;
    }

    const parsedUrl = new URL(url);
    const isHttps = parsedUrl.protocol === 'https:';

    let payload = null;
    if (body != null) {
      if (Buffer.isBuffer(body)) {
        payload = body;
      } else if (typeof body === 'string') {
        payload = Buffer.from(body, 'utf8');
      } else {
        payload = Buffer.from(body);
      }
      if (!finalHeaders['Content-Length']) {
        finalHeaders['Content-Length'] = String(payload.length);
      }
    }

    const requestOptions = {
      method,
      headers: finalHeaders,
      agent: agent || undefined,
    };

    const client = isHttps ? https : http;

    return new Promise((resolve, reject) => {
      const req = client.request(parsedUrl, requestOptions, (res) => {
        const chunks = [];
        res.on('data', (chunk) => {
          chunks.push(chunk);
        });
        res.on('end', () => {
          const buffer = Buffer.concat(chunks);
          const cookies = res.headers['set-cookie'];
          const cookieArray = cookies ? (Array.isArray(cookies) ? cookies : [cookies]) : [];
          const setCookiePromises = cookieArray.map((cookie) => jar.setCookie(cookie, url, { ignoreError: true }));
          Promise.all(setCookiePromises)
            .then(() => {
              let data = buffer;
              if (responseType !== 'arraybuffer') {
                data = buffer.toString('utf8');
              }
              resolve({
                status: res.statusCode,
                headers: res.headers,
                data,
              });
            })
            .catch(reject);
        });
      });
      req.on('error', reject);
      if (payload) {
        req.write(payload);
      }
      req.end();
    });
  };
}

async function ensureTesseractLanguages(targetDir, request) {
  await fs.mkdir(targetDir, { recursive: true });
  const languages = ['por', 'eng'];
  for (const lang of languages) {
    const destPath = path.join(targetDir, `${lang}.traineddata`);
    try {
      await fs.access(destPath);
      continue;
    } catch (err) {
      if (err.code !== 'ENOENT') {
        throw err;
      }
    }

    const url = `https://tessdata.projectnaptha.com/4.0.0/${lang}.traineddata.gz`;
    console.log(`Downloading OCR language data for ${lang}...`);
    const response = await request(url, { responseType: 'arraybuffer' });
    if (response.status !== 200) {
      throw new Error(`Failed to download ${lang} language data (HTTP ${response.status})`);
    }
    const decompressed = await gunzip(Buffer.from(response.data));
    await fs.writeFile(destPath, decompressed);
  }
}

async function fetchLoginPage(request) {
  let currentUrl = LOGIN_ENTRY_URL;

  const debug = process.env.DEBUG_LOGIN === '1';

  for (let hop = 0; hop < 30; hop += 1) {
    const resp = await request(currentUrl);

    if (debug) {
      console.log(`login hop ${hop}: status ${resp.status} -> ${resp.headers.location || 'none'}`);
    }

    if (resp.status === 200) {
      return { html: resp.data, url: currentUrl };
    }

    if (resp.status >= 300 && resp.status < 400 && resp.headers.location) {
      currentUrl = new URL(resp.headers.location, currentUrl).toString();
      continue;
    }

    if (resp.status === 503) {
      await sleep(Math.min(2000, 200 * (hop + 1)));
      continue;
    }

    throw new Error(`Unexpected status ${resp.status} while fetching login page`);
  }

  throw new Error('Too many redirects while fetching login page');
}

async function authenticate(request, username, password) {
  const { html, url } = await fetchLoginPage(request);
  const $ = cheerio.load(html);
  const execution = $('input[name="execution"]').attr('value');
  if (!execution) {
    throw new Error('Could not find execution token on login page.');
  }

  const form = new URLSearchParams();
  form.append('username', username);
  form.append('password', password);
  form.append('execution', execution);
  form.append('_eventId', 'submit');
  form.append('geolocation', '');

  const loginResp = await request(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: form.toString(),
  });

  if (loginResp.status !== 302 || !loginResp.headers.location) {
    throw new Error(`Unexpected status ${loginResp.status} during login`);
  }

  const serviceUrl = new URL(loginResp.headers.location, url).toString();
  const serviceResp = await request(serviceUrl);
  if (serviceResp.status !== 200) {
    throw new Error(`Service ticket exchange failed with status ${serviceResp.status}`);
  }
}

async function downloadArImage(request, code) {
  const form = new URLSearchParams();
  form.append('hdnCodObjeto', code);

  const response = await request(AR_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: form.toString(),
    responseType: 'arraybuffer',
  });

  if (response.status !== 200) {
    throw new Error(`HTTP ${response.status} while retrieving AR image`);
  }

  const contentType = response.headers['content-type'] || '';
  if (!contentType.startsWith('image')) {
    const text = response.data.toString('utf8');
    throw new Error(`Unexpected response (${contentType || 'unknown'}) – ${text.substring(0, 200)}`);
  }

  return {
    buffer: Buffer.from(response.data),
    extension: contentType.includes('png') ? 'png' : 'jpg',
  };
}

function toCsvValue(value) {
  if (value == null) {
    return '';
  }
  const str = String(value);
  if (str.includes(',') || str.includes('\n') || str.includes('"')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

async function processCode(request, code, dirs, options) {
  try {
    const { buffer, extension } = await downloadArImage(request, code);
    const imagePath = path.join(dirs.imagesDir, `${code}.${extension}`);
    await fs.writeFile(imagePath, buffer);

    let reason = '';
    let ocrText = '';
    if (!options.skipOcr) {
      const processedBuffer = await sharp(buffer)
        .grayscale()
        .normalize()
        .toBuffer();

      const ocrResult = await Tesseract.recognize(processedBuffer, 'por+eng', {
        langPath: options.tesseractDataDir,
        cachePath: options.tesseractDataDir,
      });
      ocrText = ocrResult.data.text || '';
      reason = extractReturnReason(ocrText);
      await fs.writeFile(path.join(dirs.ocrDir, `${code}.txt`), ocrText, 'utf8');
    }

    console.log(`✔ ${code}${reason ? ` – ${reason}` : ''}`);
    return {
      code,
      status: 'OK',
      reason,
      imagePath,
      ocrText,
    };
  } catch (error) {
    console.error(`✖ ${code} – ${error.message}`);
    return {
      code,
      status: 'ERROR',
      error: error.message,
    };
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const codes = await loadTrackingCodes(options);
  const limitedCodes = options.limit === Infinity ? codes : codes.slice(0, options.limit);

  if (!limitedCodes.length) {
    console.error('No tracking codes to process.');
    process.exit(1);
  }

  const jar = new CookieJar(undefined, { rejectPublicSuffixes: false });
  const proxyUrl = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy;
  const request = createRequester(jar, proxyUrl);

  if (proxyUrl) {
    const undiciAgent = new UndiciProxyAgent(proxyUrl);
    globalThis.fetch = (url, options = {}) => undiciFetch(url, { ...options, dispatcher: undiciAgent });
  }

  console.log(`Logging into SGD as ${options.username}...`);
  await authenticate(request, options.username, options.password);
  console.log('Login successful.');

  const outputDir = options.outputDir;
  const dirs = await ensureDirectories(outputDir);
  let executionOptions = { ...options };
  if (!options.skipOcr) {
    const tesseractDataDir = path.join(outputDir, 'tesseract-data');
    await ensureTesseractLanguages(tesseractDataDir, request);
    executionOptions = { ...options, tesseractDataDir };
  }

  const limit = pLimit(options.concurrency);
  const results = await Promise.all(
    limitedCodes.map((code) => limit(() => processCode(request, code, dirs, executionOptions))),
  );

  const csvRows = ['code,status,reason,imagePath'];
  const jsonResults = [];
  for (const result of results) {
    if (result.status === 'OK') {
      csvRows.push([
        toCsvValue(result.code),
        toCsvValue(result.status),
        toCsvValue(result.reason),
        toCsvValue(path.relative(outputDir, result.imagePath)),
      ].join(','));
      jsonResults.push({
        code: result.code,
        status: result.status,
        reason: result.reason,
        imagePath: path.relative(outputDir, result.imagePath),
        ocrText: options.skipOcr ? undefined : result.ocrText,
      });
    } else {
      csvRows.push([
        toCsvValue(result.code),
        toCsvValue(result.status),
        toCsvValue(result.error),
        '',
      ].join(','));
      jsonResults.push({
        code: result.code,
        status: result.status,
        error: result.error,
      });
    }
  }

  await fs.writeFile(path.join(outputDir, 'results.csv'), `${csvRows.join('\n')}\n`, 'utf8');
  await fs.writeFile(path.join(outputDir, 'results.json'), `${JSON.stringify(jsonResults, null, 2)}\n`, 'utf8');

  console.log(`Finished. ${results.filter((r) => r.status === 'OK').length} succeeded, ${results.filter((r) => r.status !== 'OK').length} failed.`);
  console.log(`Results saved to ${outputDir}`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}

module.exports = {
  extractReturnReason,
  stripAccents,
  loadTrackingCodes,
};
