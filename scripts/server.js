#!/usr/bin/env node

const path = require('path');
const express = require('express');
const { runFetcher } = require('./fetch_ar');

const app = express();
const ROOT_DIR = path.join(__dirname, '..');
const PORT = Number(process.env.PORT) || 3000;

app.use(express.json({ limit: '2mb' }));
app.use(express.static(ROOT_DIR));

function parseCodes(input) {
  if (!input) {
    return [];
  }
  if (Array.isArray(input)) {
    return input.map((code) => String(code).trim()).filter(Boolean);
  }
  return String(input)
    .split(/[\r\n,]+/)
    .map((code) => code.trim())
    .filter(Boolean);
}

app.post('/api/fetch-ar', async (req, res) => {
  req.setTimeout(0);
  res.setTimeout(0);

  const payload = req.body || {};
  const username = typeof payload.username === 'string' ? payload.username.trim() : '';
  const password = typeof payload.password === 'string' ? payload.password : '';

  if (!username || !password) {
    res.status(400).json({ success: false, error: 'Username and password are required.' });
    return;
  }

  const codes = parseCodes(payload.codes);
  const runOptions = {
    username,
    password,
    skipOcr: Boolean(payload.skipOcr),
  };

  if (codes.length) {
    runOptions.codes = codes;
  }

  if (payload.limit !== undefined && payload.limit !== null && payload.limit !== '') {
    runOptions.limit = Number(payload.limit);
  }

  if (payload.concurrency !== undefined && payload.concurrency !== null && payload.concurrency !== '') {
    runOptions.concurrency = Number(payload.concurrency);
  }

  const baseOutputDir = path.join(ROOT_DIR, 'output', 'web');
  const uniqueDir = `session-${Date.now()}`;
  runOptions.outputDir = path.join(baseOutputDir, uniqueDir);

  try {
    const result = await runFetcher(runOptions);
    res.json({
      success: true,
      outputDir: path.relative(ROOT_DIR, result.outputDir),
      summary: result.summary,
      results: result.results,
    });
  } catch (error) {
    console.error('Failed to process AR request:', error);
    res.status(500).json({ success: false, error: error.message || 'Unknown error' });
  }
});

app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
