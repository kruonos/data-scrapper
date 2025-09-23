const fs = require('fs/promises');
const path = require('path');
const os = require('os');
const { execFile } = require('child_process');
const { promisify } = require('util');
const sharp = require('sharp');
const Tesseract = require('tesseract.js');
const { fetch: undiciFetch } = require('undici');
const zlib = require('zlib');

const execFileAsync = promisify(execFile);
const gunzipAsync = promisify(zlib.gunzip);

const LANGUAGE_DOWNLOADS = [
  { lang: 'por', url: 'https://tessdata.projectnaptha.com/4.0.0/por.traineddata.gz' },
  { lang: 'eng', url: 'https://tessdata.projectnaptha.com/4.0.0/eng.traineddata.gz' },
];

const STATUS_PATTERNS = [
  {
    label: 'ausente',
    displayName: 'Ausente',
    patterns: [/AUSENTE/i, /NAO (HA|H[AÁ]) PESSOA/i],
    keywords: ['AUSENTE'],
    wordHints: ['AUSENTE'],
  },
  {
    label: 'nao_procurado',
    displayName: 'Não Procurado',
    patterns: [/NA[ÃA]O\s+PROCURADO/i, /N[ÃA]O\s+PROCUROU/i],
    keywords: ['NAOPROCURADO', 'NAOPROCUROU'],
    wordHints: ['PROCURADO', 'PROCUROU'],
  },
  {
    label: 'mudou_se',
    displayName: 'Mudou-se',
    patterns: [/MUDOU[-\s]?SE/i, /[MN][UUV]DOU[-\s]?SE/i, /[MI]DOU[-\s]?SE/i],
    keywords: ['MUDOUSE', 'MUDOSE', 'IDOUSE', 'MUDOU5E'],
    wordHints: ['MUDOU', 'MUDO', 'MUDOU-SE'],
  },
  {
    label: 'endereco_insuficiente',
    displayName: 'Endereço Insuficiente',
    patterns: [/ENDERE[ÇC]O\s+INSUF/i, /ENDERE[ÇC]O\s+INCOMPLETO/i],
    keywords: ['ENDERECOINSUF', 'ENDERECOINCOMPLETO', 'ENDERECOINSUFICIENTE'],
    wordHints: ['INSUF', 'INCOMPLETO'],
  },
  {
    label: 'nao_existe_numero',
    displayName: 'Não existe o número',
    patterns: [/N[ÃA]O\s+EXISTE\s+O?\s+N[ÚU]MERO/i, /N[ÚU]MERO\s+INEXISTENTE/i],
    keywords: ['NAOEXISTEONUMERO', 'NAOEXISTENUMERO', 'NUMEROINEXISTENTE'],
    wordHints: ['NUMERO', 'NUMER'],
  },
  {
    label: 'desconhecido',
    displayName: 'Desconhecido',
    patterns: [/DESCONHECIDO/i],
    keywords: ['DESCONHECIDO'],
    wordHints: ['DESCONHECIDO'],
  },
  {
    label: 'recusado',
    displayName: 'Recusado',
    patterns: [/RECUSAD[AO]/i, /RECUSA[DN]?O?/i],
    keywords: ['RECUSADO', 'RECUSA'],
    wordHints: ['RECUS'],
  },
  {
    label: 'falecido',
    displayName: 'Falecido',
    patterns: [/FALECIDO/i],
    keywords: ['FALECIDO'],
    wordHints: ['FALECIDO'],
  },
];

const STATUS_LOOKUP = new Map(STATUS_PATTERNS.map((entry) => [entry.label, entry]));

const SIGNATURE_REGION = {
  left: 0.15,
  top: 0.7,
  width: 0.25,
  height: 0.2,
};

const SIGNATURE_THRESHOLD = 0.08;
const MARK_DARKNESS_THRESHOLD = 0.9;
const MARK_MIN_CONTRAST = 0;
const MARK_MIN_SCORE = 0.02;
const ROI_REGION = {
  left: 0.25,
  top: 0.32,
  width: 0.45,
  height: 0.32,
  outputWidth: 320,
  outputHeight: 160,
};

function stripAccents(text) {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function extractWordsFromTsv(tsv) {
  if (typeof tsv !== 'string' || !tsv.trim()) {
    return [];
  }
  const lines = tsv.split(/\r?\n/);
  const words = [];
  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line || !line.trim()) {
      continue;
    }
    const parts = line.split('\t');
    if (parts.length < 12) {
      continue;
    }
    const level = Number(parts[0]);
    if (level !== 5) {
      continue;
    }
    const text = parts.slice(11).join('\t').trim();
    if (!text) {
      continue;
    }
    const left = Number(parts[6]);
    const top = Number(parts[7]);
    const width = Number(parts[8]);
    const height = Number(parts[9]);
    if (!Number.isFinite(left) || !Number.isFinite(top) || !Number.isFinite(width) || !Number.isFinite(height)) {
      continue;
    }
    words.push({
      text,
      bbox: {
        x0: left,
        y0: top,
        x1: left + width,
        y1: top + height,
      },
    });
  }
  return words;
}

function findStatusFromText(text) {
  if (!text) {
    return null;
  }
  const normalized = stripAccents(text).toUpperCase();
  const compact = normalized.replace(/[^A-Z0-9]/g, '');
  for (const entry of STATUS_PATTERNS) {
    for (const pattern of entry.patterns) {
      if (pattern.test(normalized)) {
        const match = normalized.match(pattern);
        return {
          label: entry.label,
          displayName: entry.displayName,
          matchedText: match ? match[0] : pattern.source,
        };
      }
    }
    if (entry.keywords) {
      for (const keyword of entry.keywords) {
        if (compact.includes(keyword)) {
          return {
            label: entry.label,
            displayName: entry.displayName,
            matchedText: keyword,
          };
        }
      }
    }
  }
  return null;
}

async function ensureLanguages(targetDir) {
  await fs.mkdir(targetDir, { recursive: true });
  for (const { lang, url } of LANGUAGE_DOWNLOADS) {
    const destination = path.join(targetDir, `${lang}.traineddata`);
    try {
      await fs.access(destination);
      continue;
    } catch (err) {
      if (err.code !== 'ENOENT') {
        throw err;
      }
    }

    const localCopy = path.join(__dirname, '..', 'tessdata', `${lang}.traineddata`);
    try {
      const buffer = await fs.readFile(localCopy);
      await fs.writeFile(destination, buffer);
      continue;
    } catch (localErr) {
      if (localErr.code !== 'ENOENT') {
        throw localErr;
      }
    }

    const response = await undiciFetch(url).catch((err) => {
      throw new Error(`Failed to download ${lang} language data: ${err.message}`);
    });
    if (!response.ok) {
      throw new Error(`Failed to download ${lang} language data (HTTP ${response.status})`);
    }
    const compressed = Buffer.from(await response.arrayBuffer());
    const decompressed = await gunzipAsync(compressed);
    await fs.writeFile(destination, decompressed);
  }
}

function detectFileType(buffer, originalName = '') {
  if (buffer.length >= 4 && buffer.slice(0, 4).toString('ascii') === '%PDF') {
    return 'pdf';
  }
  if (buffer.length >= 8 && buffer.slice(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return 'png';
  }
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xd8) {
    return 'jpg';
  }
  const lower = originalName.toLowerCase();
  if (lower.endsWith('.pdf')) return 'pdf';
  if (lower.endsWith('.png')) return 'png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'jpg';
  return 'unknown';
}

async function convertPdfToPng(buffer, workDir) {
  const inputPath = path.join(workDir, 'input.pdf');
  const outputBase = path.join(workDir, 'page');
  await fs.writeFile(inputPath, buffer);
  await execFileAsync('pdftoppm', [inputPath, outputBase, '-png', '-singlefile', '-r', '200']);
  const outputPath = `${outputBase}.png`;
  return outputPath;
}

async function bufferToTempFile(buffer, workDir, extension) {
  const filePath = path.join(workDir, `input.${extension}`);
  await fs.writeFile(filePath, buffer);
  return filePath;
}

async function loadImageBuffer(sourcePath) {
  const image = sharp(sourcePath);
  const metadata = await image.metadata();
  const processed = await image
    .ensureAlpha()
    .removeAlpha()
    .grayscale()
    .normalize()
    .median(1)
    .toBuffer();
  const processedMeta = await sharp(processed).metadata();
  return { buffer: processed, metadata: processedMeta };
}

async function estimateSignatureScore(imageBuffer, metadata) {
  const image = sharp(imageBuffer).greyscale();
  const { width, height } = metadata;
  if (!width || !height) {
    return 0;
  }
  const left = Math.floor(width * SIGNATURE_REGION.left);
  const top = Math.floor(height * SIGNATURE_REGION.top);
  const regionWidth = Math.max(1, Math.floor(width * SIGNATURE_REGION.width));
  const regionHeight = Math.max(1, Math.floor(height * SIGNATURE_REGION.height));
  const region = await image
    .extract({ left, top, width: regionWidth, height: regionHeight })
    .raw()
    .toBuffer();
  let darkPixels = 0;
  for (const value of region) {
    if (value < 180) {
      darkPixels += 1;
    }
  }
  return darkPixels / region.length;
}

async function runOcr(buffer, tessdataDir) {
  const result = await Tesseract.recognize(buffer, 'por+eng', {
    langPath: tessdataDir,
    cachePath: tessdataDir,
  });
  return result.data;
}

async function measureRegionDarkness(imageBuffer, bbox, metadata) {
  if (!bbox || !metadata.width || !metadata.height) {
    return 1;
  }

  const baseWidth = metadata.width;
  const baseHeight = metadata.height;
  const bboxWidth = Math.max(1, bbox.x1 - bbox.x0);
  const bboxHeight = Math.max(1, bbox.y1 - bbox.y0);
  const expandX = Math.max(Math.floor(bboxWidth * 0.8), Math.floor(baseWidth * 0.015));
  const expandY = Math.max(Math.floor(bboxHeight * 1.2), Math.floor(baseHeight * 0.02));

  const left = Math.max(0, Math.floor(bbox.x0) - expandX);
  const top = Math.max(0, Math.floor(bbox.y0) - Math.floor(expandY / 2));
  const width = Math.min(baseWidth - left, Math.max(3, expandX));
  const height = Math.min(baseHeight - top, Math.max(3, bboxHeight + expandY));

  const region = await sharp(imageBuffer)
    .extract({ left, top, width, height })
    .raw()
    .toBuffer();

  if (!region.length) {
    return 1;
  }

  let sum = 0;
  for (const value of region) {
    sum += value;
  }

  return sum / (region.length * 255);
}

async function extractRoi(buffer, metadata) {
  const width = metadata.width;
  const height = metadata.height;
  if (!width || !height) {
    return Buffer.alloc(0);
  }

  const left = Math.max(0, Math.floor(width * ROI_REGION.left));
  const top = Math.max(0, Math.floor(height * ROI_REGION.top));
  const regionWidth = Math.min(width - left, Math.max(1, Math.floor(width * ROI_REGION.width)));
  const regionHeight = Math.min(height - top, Math.max(1, Math.floor(height * ROI_REGION.height)));

  return sharp(buffer)
    .extract({ left, top, width: regionWidth, height: regionHeight })
    .resize(ROI_REGION.outputWidth, ROI_REGION.outputHeight, { fit: 'fill' })
    .raw()
    .toBuffer();
}

const MARK_ANALYSIS_COLUMNS = {
  left: 0.32,
  right: 0.62,
};

const MARK_REFERENCE_POINTS = [
  { label: 'mudou_se', column: 'right', row: 0.38 },
  { label: 'mudou_se', column: 'left', row: 0.35 },
  { label: 'nao_existe_numero', column: 'left', row: 0.40 },
  { label: 'ausente', column: 'right', row: 0.64 },
  { label: 'ausente', column: 'right', row: 0.52 },
  { label: 'endereco_insuficiente', column: 'right', row: 0.33 },
];

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

async function extractRegion(imageBuffer, left, top, width, height) {
  if (width <= 0 || height <= 0) {
    return null;
  }

  const buffer = await sharp(imageBuffer)
    .extract({ left, top, width, height })
    .raw()
    .toBuffer();

  if (!buffer.length) {
    return null;
  }

  return { buffer, width, height };
}

function computeMeanFromBuffer(buffer) {
  if (!buffer || !buffer.length) {
    return 1;
  }
  let sum = 0;
  for (const value of buffer) {
    sum += value;
  }
  return sum / (buffer.length * 255);
}

function computeDiagonalFeatures(region) {
  if (!region) {
    return null;
  }

  const { buffer, width, height } = region;
  const totalPixels = width * height;
  if (!totalPixels) {
    return null;
  }

  const diagThreshold = 0.08;
  const centerThreshold = 0.2;
  let diagSum = 0;
  let diagCount = 0;
  let offDiagSum = 0;
  let offDiagCount = 0;
  let centerSum = 0;
  let centerCount = 0;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = buffer[y * width + x] / 255;
      const nx = width > 1 ? x / (width - 1) : 0;
      const ny = height > 1 ? y / (height - 1) : 0;
      const onDiag1 = Math.abs(ny - nx) <= diagThreshold;
      const onDiag2 = Math.abs(ny - (1 - nx)) <= diagThreshold;
      const onDiag = onDiag1 || onDiag2;
      if (onDiag) {
        diagSum += value;
        diagCount += 1;
      } else {
        offDiagSum += value;
        offDiagCount += 1;
      }
      if (Math.abs(nx - 0.5) <= centerThreshold && Math.abs(ny - 0.5) <= centerThreshold) {
        centerSum += value;
        centerCount += 1;
      }
    }
  }

  return {
    diagMean: diagCount ? diagSum / diagCount : 1,
    offDiagMean: offDiagCount ? offDiagSum / offDiagCount : 1,
    centerMean: centerCount ? centerSum / centerCount : 1,
    diagCoverage: diagCount / totalPixels,
  };
}

async function measureMarkCandidate(imageBuffer, metadata, reference) {
  if (!metadata.width || !metadata.height) {
    return null;
  }

  const columnFraction = MARK_ANALYSIS_COLUMNS[reference.column];
  if (typeof columnFraction !== 'number') {
    return null;
  }

  const { width, height } = metadata;
  const centerX = Math.floor(width * columnFraction);
  const centerY = Math.floor(height * reference.row);
  const sampleWidth = Math.max(6, Math.floor(width * 0.04));
  const sampleHeight = Math.max(6, Math.floor(height * 0.05));
  const left = clamp(Math.floor(centerX - sampleWidth / 2), 0, Math.max(0, width - sampleWidth));
  const top = clamp(Math.floor(centerY - sampleHeight / 2), 0, Math.max(0, height - sampleHeight));
  const actualWidth = Math.min(sampleWidth, width - left);
  const actualHeight = Math.min(sampleHeight, height - top);

  const region = await extractRegion(imageBuffer, left, top, actualWidth, actualHeight);
  if (!region) {
    return null;
  }

  const mean = computeMeanFromBuffer(region.buffer);
  const diagonalFeatures = computeDiagonalFeatures(region);

  const verticalOffset = Math.max(4, Math.floor(actualHeight * 1.4));
  const horizontalOffset = Math.max(4, Math.floor(actualWidth * 1.4));

  const neighborAreas = [
    { left, top: clamp(top - verticalOffset, 0, Math.max(0, height - actualHeight)) },
    { left, top: clamp(top + verticalOffset, 0, Math.max(0, height - actualHeight)) },
    { left: clamp(left - horizontalOffset, 0, Math.max(0, width - actualWidth)), top },
    { left: clamp(left + horizontalOffset, 0, Math.max(0, width - actualWidth)), top },
  ];

  const neighborMeans = [];
  for (const area of neighborAreas) {
    if (area.left === left && area.top === top) {
      continue;
    }
    const neighborRegion = await extractRegion(imageBuffer, area.left, area.top, actualWidth, actualHeight);
    if (neighborRegion) {
      const value = computeMeanFromBuffer(neighborRegion.buffer);
      if (Number.isFinite(value)) {
        neighborMeans.push(value);
      }
    }
  }

  const backgroundMean = neighborMeans.length
    ? neighborMeans.reduce((acc, value) => acc + value, 0) / neighborMeans.length
    : 1;

  const centerRow = metadata.height ? (top + actualHeight / 2) / metadata.height : 0;
  const rowDiff = Math.abs(centerRow - reference.row);

  return {
    label: reference.label,
    displayName: STATUS_LOOKUP.get(reference.label)?.displayName || reference.label,
    mean,
    contrast: backgroundMean - mean,
    backgroundMean,
    bbox: { left, top, width: actualWidth, height: actualHeight },
    reference,
    rowDiff,
    diagonalFeatures,
  };
}

function computeCandidateScore(candidate) {
  const contrastScore = Math.max(0, candidate.contrast) * 0.7;
  const darknessScore = Math.max(0, 1 - candidate.mean) * 0.3;
  const rowPenalty = (candidate.rowDiff || 0) * 0.2;
  return contrastScore + darknessScore - rowPenalty;
}

async function detectReasonByVisualMarks(imageBuffer, metadata) {
  const rawCandidates = [];
  for (const reference of MARK_REFERENCE_POINTS) {
    const measurement = await measureMarkCandidate(imageBuffer, metadata, reference);
    if (measurement) {
      measurement.score = computeCandidateScore(measurement);
      rawCandidates.push(measurement);
    }
  }

  const bestByLabel = new Map();
  for (const candidate of rawCandidates) {
    const existing = bestByLabel.get(candidate.label);
    if (!existing || candidate.score > existing.score) {
      bestByLabel.set(candidate.label, candidate);
    }
  }

  const aggregated = Array.from(bestByLabel.values());
  const eligible = aggregated.filter(
    (candidate) => candidate.contrast >= MARK_MIN_CONTRAST && candidate.mean <= MARK_DARKNESS_THRESHOLD,
  );

  eligible.sort((a, b) => {
    const scoreDiff = b.score - a.score;
    if (Math.abs(scoreDiff) > 1e-3) {
      return scoreDiff;
    }
    return a.mean - b.mean;
  });

  return {
    best: eligible[0] || null,
    candidates: aggregated,
    rawCandidates,
  };
}

function buildResponse({ statusMatch, signatureScore, explanation, ocrPreview, markMatch }) {
  if (statusMatch) {
    const confidence = statusMatch.source === 'mark'
      ? Math.min(0.95, 0.55 + (markMatch ? markMatch.contrast * 1.6 : 0))
      : 0.9;

    const response = {
      label: statusMatch.label,
      displayName: statusMatch.displayName,
      confidence,
      reason:
        explanation
        || (statusMatch.source === 'mark'
          ? `Marca detectada no campo "${statusMatch.displayName}".`
          : 'Motivo identificado no OCR.'),
      signatureScore,
      matchedText: statusMatch.matchedText,
      ocrText: ocrPreview,
    };
    if (statusMatch.source) {
      response.source = statusMatch.source;
    }
    if (markMatch) {
      response.markAnalysis = {
        label: markMatch.label,
        displayName: markMatch.displayName,
        mean: markMatch.mean,
        contrast: markMatch.contrast,
        bbox: markMatch.bbox,
      };
    }
    return response;
  }

  if (signatureScore >= SIGNATURE_THRESHOLD) {
    return {
      label: 'positivo',
      displayName: 'Positivo (assinatura identificada)',
      confidence: Math.min(1, signatureScore / 0.12),
      reason: explanation || 'Assinatura detectada no campo do recebedor.',
      signatureScore,
      matchedText: null,
      ocrText: ocrPreview,
    };
  }

  return {
    label: 'indefinido',
    displayName: 'Indefinido',
    confidence: 0.2,
    reason: explanation || 'Não foi possível identificar um motivo nem assinatura.',
    signatureScore,
    matchedText: null,
    ocrText: ocrPreview,
  };
}

async function classifyArBuffer(buffer, options = {}) {
  if (!buffer || !buffer.length) {
    throw new Error('Arquivo vazio.');
  }

  const workDir = await fs.mkdtemp(path.join(os.tmpdir(), 'ar-classifier-'));
  try {
    const fileType = detectFileType(buffer, options.filename || '');
    let imagePath;

    if (fileType === 'pdf') {
      try {
        imagePath = await convertPdfToPng(buffer, workDir);
      } catch (err) {
        throw new Error(`Falha ao converter PDF para imagem: ${err.message}`);
      }
    } else if (fileType === 'png' || fileType === 'jpg') {
      imagePath = await bufferToTempFile(buffer, workDir, fileType);
    } else {
      throw new Error('Formato de arquivo não suportado. Use PDF, PNG ou JPG.');
    }

    const { buffer: processedBuffer, metadata } = await loadImageBuffer(imagePath);

    const tessdataDir = path.join(workDir, 'tessdata');
    await ensureLanguages(tessdataDir);

    const ocrData = await runOcr(processedBuffer, tessdataDir);
    const ocrText = ocrData.text || '';
    const ocrPreview = ocrText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(0, 200)
      .join('\n');

    let statusMatch = findStatusFromText(ocrText);
    let explanation = null;
    if (statusMatch) {
      statusMatch.source = 'ocr';
      if (statusMatch.matchedText) {
        explanation = `Motivo identificado no OCR: "${statusMatch.matchedText.trim()}".`;
      } else {
        explanation = 'Motivo identificado no OCR.';
      }
    }

    const markDetection = await detectReasonByVisualMarks(processedBuffer, metadata);
    const markMatch = markDetection.best;
    let overriddenMark = null;
    let overriddenOcr = null;
    if (markMatch) {
      const markStatus = {
        label: markMatch.label,
        displayName: markMatch.displayName,
        matchedText: markMatch.displayName,
        source: 'mark',
      };
      const markScore = typeof markMatch.score === 'number' ? markMatch.score : 0;
      if (!statusMatch && markScore >= MARK_MIN_SCORE) {
        statusMatch = markStatus;
        explanation = `Marca detectada no campo "${markMatch.displayName}".`;
      } else if (statusMatch.label === markStatus.label) {
        explanation = explanation
          ? `${explanation} Marcação visual identificada no mesmo campo.`
          : `Marcação visual identificada no campo "${markMatch.displayName}".`;
        statusMatch = markStatus;
      } else if (statusMatch.source === 'ocr' && markScore >= 0.04) {
        overriddenOcr = statusMatch;
        statusMatch = markStatus;
        explanation = `Marcação visual predominante em "${markMatch.displayName}" substituiu o texto OCR.`;
      }
    }

    const signatureScore = await estimateSignatureScore(processedBuffer, metadata);
    const hasStrongSignature = signatureScore >= SIGNATURE_THRESHOLD;
    if (statusMatch && statusMatch.source === 'mark' && hasStrongSignature) {
      overriddenMark = markMatch || null;
      explanation = 'Assinatura detectada com alta confiança; classificando como positivo.';
      statusMatch = null;
    }

    const analysis = buildResponse({
      statusMatch,
      signatureScore,
      explanation,
      ocrPreview,
      markMatch,
    });
    analysis.signatureThreshold = SIGNATURE_THRESHOLD;
    analysis.fileType = fileType;
    analysis.width = metadata.width;
    analysis.height = metadata.height;
    analysis.ocrFullText = ocrText;
    analysis.markCandidates = markDetection.candidates;
    analysis.markCandidatesRaw = markDetection.rawCandidates;
    if (markMatch) {
      analysis.markMatch = markMatch;
    }
    if (overriddenMark) {
      analysis.markOverride = overriddenMark;
    }
    if (overriddenOcr) {
      analysis.ocrOverride = overriddenOcr;
    }

    return analysis;
  } finally {
    await fs.rm(workDir, { recursive: true, force: true });
  }
}

module.exports = {
  classifyArBuffer,
  STATUS_PATTERNS,
  SIGNATURE_THRESHOLD,
};
