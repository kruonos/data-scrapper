#!/usr/bin/env node

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

function listTrackedFiles() {
  const output = execSync('git ls-files', { encoding: 'utf8' });
  return output
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function findConflictMarkers(filePath) {
  const absolutePath = path.resolve(filePath);
  let content;
  try {
    content = fs.readFileSync(absolutePath, 'utf8');
  } catch (error) {
    return [];
  }

  const markers = ['<<<<<<<', '=======', '>>>>>>>'];
  const offenders = [];

  const lines = content.split(/\r?\n/);
  lines.forEach((line, index) => {
    for (const marker of markers) {
      if (line.startsWith(marker)) {
        offenders.push({ marker, line: index + 1 });
      }
    }
  });

  return offenders;
}

function main() {
  const files = listTrackedFiles();
  const problems = [];

  for (const file of files) {
    const offenders = findConflictMarkers(file);
    if (offenders.length) {
      problems.push({ file, offenders });
    }
  }

  if (problems.length) {
    console.error('Detected merge conflict markers in the following files:');
    for (const problem of problems) {
      for (const offender of problem.offenders) {
        console.error(`  ${problem.file}:${offender.line} contains "${offender.marker}"`);
      }
    }
    process.exit(1);
  }

  console.log('No merge conflict markers detected.');
}

main();
